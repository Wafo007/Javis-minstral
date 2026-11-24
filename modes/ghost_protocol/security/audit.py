"""ORCHESTRATEUR D'AUDIT : une session = une cible autorisee. Boucle pilotee par le moteur de decision, etat persiste a chaque etape
(reprise apres erreur), arret d'urgence, evenements vers le HUD. Aucune etape n'est lancee sans passer par la Garde."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path

from modes.ghost_protocol.security import (agent_api, agent_code, agent_recon, agent_reseau, agent_validation, agent_vuln, agent_web, decision,
                                           outils as O, rapport)
from modes.ghost_protocol.security.contexte import AuditInterrompu, Contexte
from modes.ghost_protocol.security.http_cadre import ClientCadre
from modes.ghost_protocol.security.journal import ArretUrgence, Journal
from modes.ghost_protocol.security.modele import Gravite, ORDRE_GRAVITE, Resultat, Statut
from modes.ghost_protocol.security.perimetre import Garde, RefusPerimetre

LOG = logging.getLogger("jarvis.ghost.secu")
AGENTS_PAR_ETAPE = {"recon": ["RECON"], "web": ["WEB"], "api": ["API"], "reseau": ["RÉSEAU"], "nuclei": [], "zap": [], "code": ["CODE"],
                    "gitleaks": [], "semgrep": [], "trivy": [], "depcheck": [], "validation": ["VALIDATION"], "correlation": ["VULNÉRABILITÉS"], "rapport": ["REPORTING"]}
MODES = {"complet", "recon", "vulnerabilites", "validation", "rapport"}


class Audit:
    def __init__(self, registre, dossier: Path, emettre=None, conseiller=None, osv_transport=None, transport_http=None, rps: float = 8.0,
                 budget: int = 800, outils: dict | None = None, resolveur=None, pdf: bool = True):
        self.registre, self.dossier = registre, Path(dossier)
        self.emettre_hud = emettre or (lambda s: None)
        self.conseiller = conseiller
        self.osv_transport = osv_transport or agent_code.transport_osv
        self.transport_http, self.rps, self.budget = transport_http, rps, budget
        self.outils = outils
        self.resolveur = resolveur
        self.pdf = pdf
        self.session: dict = {}
        self.ctx: Contexte | None = None
        self.etat = "AUCUN"
        self.arret = ArretUrgence(self.dossier / "ARRET_URGENCE")
        self._thread = None
        self._verrou = threading.RLock()
        self._actifs = {"agents": [], "outils": [], "etape": ""}
        self._dernier_emit = 0.0
        self.historique: list = []
        self.rapports: dict = {}

    # ------------------------------------------------------------------ preparation
    def preparer(self, cible_ou_url: str, code: bool = False) -> tuple:
        """Verifie le perimetre (aucun trafic envoye) et prepare la session. -> (ok, message)."""
        with self._verrou:
            if self.en_cours:
                return False, "un audit est déjà en cours"
            if code:
                cible = next((c for c in self.registre.lister(True) if c.type == "code_local" and (c.chemin_code == cible_ou_url or c.id == cible_ou_url)), None)
                raison = "dossier de code non enregistré : enregistrez-le d'abord (scripts/security_cible.py code)"
            else:
                cible, raison = self.registre.trouver(cible_ou_url)
            if cible is None:
                self._noter(f"REFUS : {raison}")
                return False, raison
            sid = "A-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
            dossier = self.dossier / "audits" / sid
            dossier.mkdir(parents=True, exist_ok=True)
            self.arret.reinitialiser()
            journal = Journal(dossier / "journal.jsonl")
            kw = {"resolveur": self.resolveur} if self.resolveur else {}
            garde = Garde(cible, journal, self.arret, rps_max=self.rps, budget_requetes=self.budget, **kw)
            client = ClientCadre(garde, transport=self.transport_http) if self.transport_http else ClientCadre(garde)
            self.ctx = Contexte(cible, garde, journal, self.arret, client, emettre=self._evenement)
            self.ctx.faits["outils"] = self.outils if self.outils is not None else O.detecter()
            self.ctx.faits["osv_transport"] = self.osv_transport
            self.session = {"id": sid, "dossier": str(dossier), "cible": cible.__dict__.copy(), "debut": time.time(), "etapes": [], "ecartees": [],
                            "demandes": [], "correlations": [], "contradictions": [], "conseils": []}
            self.etat = "PRÊT"
            journal.ecrire("SESSION", id=sid, cible=cible.hote, type=cible.type, autorisation=cible.id)
            self._noter(f"Session {sid} préparée pour {cible.hote} ({cible.type}) — périmètre vérifié, aucun trafic envoyé.")
            self._sauver()
            self._emettre(force=True)
            dispo = [n for n, o in self.ctx.faits["outils"].items() if o.statut == "operationnel"]
            return True, f"Audit préparé pour {cible.hote}. Outils opérationnels : {', '.join(dispo) or 'aucun (agents natifs seulement)'}."

    @property
    def en_cours(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ execution
    def lancer(self, mode: str = "complet", attendre: bool = False, conseils_llm: bool = False) -> tuple:
        with self._verrou:
            if self.ctx is None:
                return False, "aucun audit préparé : indiquez d'abord le laboratoire à analyser"
            if self.en_cours:
                return False, "un audit est déjà en cours"
            if mode not in MODES:
                return False, f"mode inconnu : {mode}"
            self.arret.reinitialiser()
            self.etat = "EN COURS"
            self._thread = threading.Thread(target=self._boucle, args=(mode, conseils_llm), daemon=True, name="ghost-audit")
            self._thread.start()
        if attendre:
            self._thread.join()
        return True, f"audit « {mode} » lancé"

    def arreter(self, motif: str = "arrêt demandé par l'utilisatrice") -> bool:
        self.arret.declencher(motif)
        self._noter("ARRÊT D'URGENCE : " + motif)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(8)
        return not self.en_cours

    def _faites(self) -> dict:
        return {e["cle"]: e["statut"] for e in self.session.get("etapes", []) if e["statut"] in ("ok", "partiel")}

    def _boucle(self, mode: str, conseils_llm: bool):
        ctx, s = self.ctx, self.session
        erreurs = 0
        conseils = list(s.get("conseils", []))
        try:
            while True:
                if self.arret.actif():
                    raise AuditInterrompu("arrêt demandé")
                faites = self._faites()
                if mode == "validation":
                    cle = next((c for c in ("validation", "correlation") if c not in faites or c == "validation"), None)
                    etape = decision.Etape(cle, decision.CATALOGUE[cle], "étape demandée explicitement", cle.upper()) if cle and "correlation" not in faites else None
                    if "validation" in faites and "correlation" not in faites:
                        etape = decision.Etape("correlation", decision.CATALOGUE["correlation"], "étape demandée explicitement", "VULN")
                    elif "validation" not in faites:
                        etape = decision.Etape("validation", decision.CATALOGUE["validation"], "étape demandée explicitement", "VALIDATION")
                    raison = "validation terminée"
                elif mode == "rapport":
                    etape = next((decision.Etape(c, decision.CATALOGUE[c], "étape demandée explicitement", c.upper()) for c in ("correlation", "rapport") if c not in faites), None)
                    if "rapport" in faites:
                        etape = decision.Etape("rapport", decision.CATALOGUE["rapport"], "régénération demandée", "REPORTING") if mode == "rapport" and "rapport" not in faites else None
                    raison = "rapport prêt"
                else:
                    from modes.ghost_protocol.security.perimetre import Cible
                    ecartees = [decision.Ecartee(e["cle"], e["raison"]) for e in s["ecartees"]]
                    etape, raison = decision.suivante(ctx.cible, ctx.faits["outils"], ctx.faits, faites, ecartees, conseils, ctx.garde, ctx.client)
                    s["ecartees"] = [{"cle": e.cle, "raison": e.raison} for e in ecartees]
                    if etape and mode == "recon" and etape.cle != "recon":
                        etape, raison = None, "reconnaissance terminée"
                    if etape and mode == "vulnerabilites" and etape.cle in ("validation", "correlation", "rapport"):
                        etape, raison = None, "analyse terminée (validation et rapport à demander ensuite)"
                    if etape is None and "reseau" in ("reseau",) and "reseau" not in ctx.cible.actions and ctx.cible.type != "code_local":
                        dem = "Scan réseau non autorisé pour cette cible : ré-enregistrez la cible avec l'action « reseau » pour l'autoriser."
                        if dem not in s["demandes"]:
                            s["demandes"].append(dem)
                if etape is None:
                    self._noter(raison)
                    break
                ok = self._executer(etape, mode)
                erreurs = 0 if ok else erreurs + 1
                if erreurs >= 3:
                    raise RuntimeError("3 étapes consécutives en erreur : audit arrêté (reprise possible)")
                if etape.cle == "recon" and ctx.faits.get("joignable") and self.conseiller is not None and conseils_llm and not conseils:
                    conseils = self._conseils(ctx)
            self.etat = "TERMINÉ"
        except AuditInterrompu as e:
            self.etat = "ARRÊTÉ"
            self._noter(f"audit interrompu : {e}")
            self._etape_terminee("interrompu", "arrêt d'urgence / arrêt demandé")
        except Exception as e:
            LOG.exception("audit")
            self.etat = "ERREUR"
            self._noter(f"erreur : {type(e).__name__}: {str(e)[:140]}")
        finally:
            self._actifs = {"agents": [], "outils": [], "etape": ""}
            s["fin"] = time.time()
            s["etat"] = self.etat
            self._sauver()
            self._emettre(force=True)

    def _conseils(self, ctx) -> list:
        try:
            dispo = [c for c in ("nuclei", "zap", "depcheck") if c in decision.CATALOGUE]
            conseils = [c for c in self.conseiller.proposer(ctx.faits, dispo) if c in dispo]
            self.session["conseils"] = conseils
            self._noter(f"conseiller IA : suggestions {conseils or 'aucune'} (le moteur reste maître de la décision)")
            return conseils
        except Exception as e:
            ctx.limiter(f"conseiller IA indisponible ({type(e).__name__}) : plan 100 % déterministe")
            return []

    def _executer(self, etape, mode) -> bool:
        ctx, s = self.ctx, self.session
        self._actifs = {"agents": AGENTS_PAR_ETAPE.get(etape.cle, []), "outils": [etape.cle] if etape.cle in ("nuclei", "zap", "gitleaks", "semgrep", "trivy", "depcheck") else [],
                        "etape": etape.titre}
        self._noter(f"▶ {etape.titre} — {etape.pourquoi}")
        self._emettre(force=True)
        debut = time.time()
        statut, resume = "ok", ""
        try:
            resume = self._appeler(etape.cle)
        except AuditInterrompu:
            raise
        except RefusPerimetre as e:
            statut, resume = "refuse", f"refus du périmètre : {e}"
            if self.arret.actif():
                raise AuditInterrompu("arrêt d'urgence")
        except Exception as e:
            LOG.exception("etape %s", etape.cle)
            statut, resume = "erreur", f"{type(e).__name__}: {str(e)[:160]}"
            ctx.limiter(f"étape « {etape.cle} » en erreur : {resume}")
        self._etape_terminee(statut, resume, etape, round(time.time() - debut, 1))
        self._sauver()
        self._emettre(force=True)
        return statut in ("ok", "refuse")

    def _etape_terminee(self, statut, resume, etape=None, duree=0.0):
        self.session["etapes"].append({"cle": etape.cle if etape else "-", "statut": statut, "pourquoi": etape.pourquoi if etape else "", "resume": resume, "duree": duree})
        self._noter(f"{'✔' if statut == 'ok' else '✖'} {etape.cle if etape else ''} : {resume}"[:200])

    def _appeler(self, cle: str) -> str:
        ctx = self.ctx
        outils = ctx.faits["outils"]

        def utilise(nom, res):
            if nom in outils and res and res.get("code") is not None:
                outils[nom].valide_en_reel = True
        if cle == "recon":
            c = agent_recon.reconnaitre(ctx)
            return f"{len(c.pages)} pages, {len(c.formulaires)} formulaires, {len(c.endpoints)} endpoints, {len(c.technologies)} technologies" if ctx.faits.get("joignable") else "cible injoignable"
        if cle == "web":
            agent_web.analyser(ctx)
            return f"{sum(1 for r in ctx.resultats.values() if r.agent == 'WEB')} résultat(s) web"
        if cle == "api":
            agent_api.analyser(ctx)
            return f"{ctx.faits.get('api_testes', 0)} endpoints testés"
        if cle == "reseau":
            if outils.get("nmap") and outils["nmap"].statut == "operationnel":
                res = O.lancer_nmap(ctx, outils["nmap"])
                utilise("nmap", res)
                return f"nmap : {res.get('ports_ouverts', '?')} ports ouverts"
            agent_reseau.analyser(ctx)
            return f"scan TCP natif : ports ouverts {ctx.faits.get('ports_ouverts', [])}"
        if cle in O.LANCEURS and cle != "nmap":
            nom = {"depcheck": "dependency-check"}.get(cle, cle)
            res = O.LANCEURS[nom](ctx, outils[nom])
            utilise(nom, res)
            return f"{nom} {res.get('version', '')} : {res.get('resultats', 0)} résultat(s)" + (" (arrêté par délai)" if res.get("expire") else "")
        if cle == "depcheck":
            res = O.lancer_dependency_check(ctx, outils["dependency-check"])
            utilise("dependency-check", res)
            return f"dependency-check : {res.get('resultats', 0)} résultat(s)"
        if cle == "code":
            agent_code.analyser(ctx, self.osv_transport, secrets="gitleaks" not in self._faites())
            return f"{ctx.faits.get('code', {}).get('fichiers', 0)} fichiers analysés"
        if cle == "validation":
            b = agent_validation.valider(ctx)
            ctx.faits["bilan_validation"] = b
            return f"{b['confirmes']} confirmés, {b['reproduits']} reproduits, {b['faux_positifs']} faux positifs écartés, {b['non_concluants']} non concluants, {b['inchanges']} non reverifiables"
        if cle == "correlation":
            c = agent_vuln.correler(ctx)
            self.session["correlations"], self.session["contradictions"] = c["correlations"], c["contradictions"]
            return f"risque {c['score']['niveau']} ({c['score']['valeur']}/100), {len(c['correlations'])} corrélation(s)"
        if cle == "rapport":
            return self._rapport()
        raise ValueError("étape inconnue : " + cle)

    # ------------------------------------------------------------------ rapport
    def _rapport(self) -> str:
        ctx, s = self.ctx, self.session
        texte_ia = ""
        if self.conseiller is not None:
            try:
                texte_ia = str(self.conseiller.resumer(ctx.faits, agent_vuln.synthese(list(ctx.resultats.values()))))[:1500]
            except Exception as e:
                ctx.limiter(f"synthèse IA indisponible ({type(e).__name__}) : rapport sans texte généré")
        s["observations"], s["limites"] = list(ctx.observations), list(ctx.limites)
        s["faits"] = {k: v for k, v in ctx.faits.items() if k not in ("outils", "osv_transport")}
        s["outils"] = {n: {**o.vers_dict(), "utilise": o.valide_en_reel} for n, o in ctx.faits["outils"].items()}
        s["duree_s"] = round(time.time() - s["debut"], 1)
        rp = rapport.construire(s, list(ctx.resultats.values()), texte_ia)
        d = Path(s["dossier"])
        (d / "rapport.json").write_text(rapport.vers_json(rp), encoding="utf-8")
        (d / "rapport.html").write_text(rapport.vers_html(rp), encoding="utf-8")
        self.rapports = {"json": str(d / "rapport.json"), "html": str(d / "rapport.html")}
        msg = "JSON + HTML"
        if self.pdf:
            ok, m = rapport.vers_pdf(d / "rapport.html", d / "rapport.pdf")
            if ok:
                self.rapports["pdf"] = str(d / "rapport.pdf")
                msg += " + PDF"
            else:
                ctx.limiter(m)
                msg += f" (PDF : {m})"
        s["rapports"] = self.rapports
        return f"rapports : {msg}"

    # ------------------------------------------------------------------ etat, HUD, persistance
    def _noter(self, texte: str):
        self.historique.append(f"{time.strftime('%H:%M:%S')} {texte}")
        del self.historique[:-60]
        if self.ctx:
            self.ctx.journal.ecrire("NOTE", texte=texte)
        self._emettre()

    def _evenement(self, type_: str, r=None):
        if type_ == "resultat":
            self._emettre()

    def snapshot(self) -> dict:
        res = list(self.ctx.resultats.values()) if self.ctx else []
        faites = self._faites()
        total = len(faites) + (0 if self.etat in ("TERMINÉ", "ARRÊTÉ", "ERREUR") else max(1, 6 - len(faites)))
        prog = 1.0 if self.etat == "TERMINÉ" else min(0.95, len(faites) / max(total, 1)) if self.etat == "EN COURS" else (len(faites) / max(total, 1) if faites else 0.0)
        confirmes = [r for r in res if r.statut == Statut.CONFIRME]
        potentiels = [r for r in res if r.statut in (Statut.POTENTIEL, Statut.A_VERIFIER, Statut.REPRODUIT)]
        graves = {g.value: sum(1 for r in res if r.gravite == g and r.statut != Statut.FAUX_POSITIF) for g in Gravite}
        rang = {Statut.CONFIRME: 0, Statut.REPRODUIT: 1}
        recents = sorted((r for r in res if r.statut != Statut.FAUX_POSITIF), key=lambda r: (rang.get(r.statut, 2), -ORDRE_GRAVITE.get(r.gravite, 0), -r.horodatage))[:6]
        return {"etat": self.etat, "cible": self.ctx.cible.hote if self.ctx else "", "type": self.ctx.cible.type if self.ctx else "",
                "etape": self._actifs["etape"], "agents": self._actifs["agents"], "outils": self._actifs["outils"], "progression": round(prog, 3),
                "potentiels": len(potentiels), "confirmes": len(confirmes), "total": len(res), "gravites": graves,
                "derniers": [{"id": r.id, "titre": r.titre[:70], "gravite": r.gravite.value, "statut": r.statut.value} for r in recents],
                "historique": self.historique[-8:], "requetes": self.ctx.garde.compte if self.ctx else 0,
                "outils_dispo": {n: o.statut for n, o in (self.ctx.faits.get("outils") or {}).items()} if self.ctx else {},
                "rapports": self.rapports}

    def _emettre(self, force: bool = False):
        now = time.time()
        if not force and now - self._dernier_emit < 0.25:
            return
        self._dernier_emit = now
        try:
            self.emettre_hud(self.snapshot())
        except Exception:
            LOG.debug("emission HUD", exc_info=True)

    def _sauver(self):
        if not self.session:
            return
        try:
            d = Path(self.session["dossier"])
            s = dict(self.session)
            s["etat"] = self.etat
            s["resultats"] = [r.vers_dict() for r in (self.ctx.resultats.values() if self.ctx else [])]
            s["observations"], s["limites"] = list(self.ctx.observations), list(self.ctx.limites)
            s["faits"] = {k: v for k, v in self.ctx.faits.items() if k not in ("outils", "osv_transport")}
            tmp = d / "session.tmp"
            tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            tmp.replace(d / "session.json")
        except Exception:
            LOG.debug("sauvegarde session", exc_info=True)

    # ------------------------------------------------------------------ reprise
    def reprendre(self, session_id: str) -> tuple:
        f = self.dossier / "audits" / session_id / "session.json"
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False, "session introuvable ou illisible"
        ok, msg = self.preparer(s["cible"]["chemin_code"] if s["cible"]["type"] == "code_local" else f"{s['cible']['schema']}://{s['cible']['hote']}:{s['cible']['ports'][0]}",
                                code=s["cible"]["type"] == "code_local")
        if not ok:
            return False, "reprise refusée : " + msg
        for d in s.get("resultats", []):
            r = Resultat.depuis_dict(d)
            self.ctx.resultats[r.id] = r
        self.ctx.observations[:] = s.get("observations", [])
        self.ctx.limites[:] = s.get("limites", [])
        self.ctx.faits.update({k: v for k, v in s.get("faits", {}).items()})
        self.session["etapes"] = [e for e in s.get("etapes", []) if e["statut"] in ("ok", "partiel")]
        self.session["ecartees"] = s.get("ecartees", [])
        self._noter(f"reprise de la session {session_id} : {len(self.session['etapes'])} étape(s) déjà faites conservées, résultats rechargés")
        return True, f"reprise depuis {session_id}"
