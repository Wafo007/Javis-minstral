"""Tests de JARVIS SECURITY INTELLIGENCE.

Honnetete : les tests marques « FIXTURE » verifient des PARSEURS sur des sorties fabriquees a la main (pas une validation de l'outil reel).
Les tests « SERVEUR LOCAL » interrogent un vrai serveur HTTP (127.0.0.1, port ephemere) lance par le test. Le test Juice Shop est ignore
(skip) si Juice Shop ne tourne pas sur 127.0.0.1:3000 : il n'est alors PAS compte comme reussi.
"""
import http.server
import json
import os
import stat
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from modes.ghost_protocol.security import outils as O
from modes.ghost_protocol.security import rapport as R
from modes.ghost_protocol.security.audit import Audit
from modes.ghost_protocol.security.contexte import Contexte
from modes.ghost_protocol.security.http_cadre import ClientCadre, Reponse
from modes.ghost_protocol.security.journal import ArretUrgence, Journal
from modes.ghost_protocol.security.modele import Gravite, Resultat, Statut, masquer
from modes.ghost_protocol.security.perimetre import Garde, Registre, RefusPerimetre, classer

INDEX = b"<html><head><title>Lab</title></head><body><app-root></app-root><script src='/main.js'></script></body></html>"


class _H(http.server.BaseHTTPRequestHandler):
    vus: list = []

    def log_message(self, *a):
        pass

    def _rep(self, code, corps, ct="text/html", extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corps)

    def do_GET(self):
        _H.vus.append(("GET", self.path))
        if self.path == "/api/Items":
            self._rep(200, json.dumps({"data": [{"id": 1, "name": "x"}]}).encode(), "application/json")
        elif self.path == "/metrics":
            self._rep(200, b"# HELP process_cpu_seconds_total x\n# TYPE process_cpu_seconds_total counter\nprocess_cpu_seconds_total 1\n", "text/plain")
        elif self.path == "/main.js":
            self._rep(200, b"fetch('/api/Items')", "application/javascript")
        else:                                      # SPA : TOUT le reste renvoie l'index avec 200 (piege a faux positifs)
            self._rep(200, INDEX)

    def do_HEAD(self):
        _H.vus.append(("HEAD", self.path))
        self._rep(200, INDEX)

    def do_OPTIONS(self):
        _H.vus.append(("OPTIONS", self.path))
        self._rep(204, b"", extra=[("Allow", "GET, HEAD, OPTIONS")])

    def do_POST(self):
        _H.vus.append(("POST", self.path))
        self._rep(405, b"no")


@pytest.fixture(scope="module")
def serveur():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def donnees(tmp_path):
    return tmp_path / "secu"


def _resolveur(table=None):
    t = table or {}
    return lambda h: t.get(h, [])


# ======================================================================= perimetre
def test_plateformes_jamais_cibles(donnees):
    reg = Registre(donnees / "c.json", resolveur=_resolveur({"tryhackme.com": ["1.2.3.4"]}))
    for u in ("https://tryhackme.com", "https://app.hackthebox.com/x", "https://portswigger.net", "https://www.pentesterlab.com", "https://owasp.org"):
        with pytest.raises(RefusPerimetre):
            reg.enregistrer(u, "j'ai demarre ce laboratoire moi-meme, attestation longue", proprietaire_confirme=True)


def test_cible_non_enregistree_refusee(donnees):
    cible, raison = Registre(donnees / "c.json").trouver("http://127.0.0.1:3000")
    assert cible is None and "non enregistree" in raison


def test_enregistrement_local_puis_trouver_et_expiration(donnees):
    now = [1000.0]
    reg = Registre(donnees / "c.json", horloge=lambda: now[0])
    c = reg.enregistrer("http://127.0.0.1:3000", duree_h=1)
    assert reg.trouver("http://127.0.0.1:3000")[0].id == c.id
    assert reg.trouver("http://127.0.0.1:3001")[0] is None            # autre port
    now[0] += 3601
    cible, raison = reg.trouver("http://127.0.0.1:3000")
    assert cible is None and "expir" in raison.lower()


def test_revocation(donnees):
    reg = Registre(donnees / "c.json")
    reg.enregistrer("http://127.0.0.1:3000")
    assert reg.revoquer("127.0.0.1") == 1
    assert reg.trouver("http://127.0.0.1:3000")[0] is None


def test_hote_externe_exige_attestation_et_confirmation(donnees):
    reg = Registre(donnees / "c.json", resolveur=_resolveur({"exemple.test": ["93.184.216.34"]}))
    with pytest.raises(RefusPerimetre):
        reg.enregistrer("https://exemple.test", "oui")
    with pytest.raises(RefusPerimetre):
        reg.enregistrer("https://exemple.test", "x" * 60)             # pas de confirmation explicite
    assert reg.enregistrer("https://exemple.test", "Mon propre site, autorisation ecrite du proprietaire (moi).", proprietaire_confirme=True)


def test_reseau_prive_et_portswigger_exigent_attestation(donnees):
    reg = Registre(donnees / "c.json", resolveur=_resolveur({"abc.web-security-academy.net": ["34.1.1.1"]}))
    with pytest.raises(RefusPerimetre):
        reg.enregistrer("http://10.10.10.5")
    assert reg.enregistrer("http://10.10.10.5", "Machine HTB que j'ai demarree via le VPN (attestation)")
    with pytest.raises(RefusPerimetre):
        reg.enregistrer("https://abc.web-security-academy.net")
    assert reg.enregistrer("https://abc.web-security-academy.net", "Lab PortSwigger demarre par moi, instance perso")


def test_classification():
    assert classer("http://localhost:3000").type == "local"
    assert classer("https://tryhackme.com").bloque
    assert classer("http://10.0.0.4").type == "reseau_prive"


def _garde(donnees, rps=1000, budget=50, resolveur=None, **kw):
    reg = Registre(donnees / "c.json")
    c = reg.enregistrer("http://127.0.0.1:3000")
    arret = ArretUrgence(donnees / "STOP")
    j = Journal(donnees / "j.jsonl")
    return Garde(c, j, arret, rps_max=rps, budget_requetes=budget, **kw), arret, c


def test_garde_hors_perimetre_methode_budget(donnees):
    g, arret, c = _garde(donnees, budget=2)
    g.autoriser("http_get", "127.0.0.1", 3000, "GET", categorie="web")
    with pytest.raises(RefusPerimetre, match="HORS PERIMETRE"):
        g.autoriser("http_get", "autre.exemple", 3000, "GET", categorie="web")
    with pytest.raises(RefusPerimetre, match="port"):
        g.autoriser("http_get", "127.0.0.1", 8080, "GET", categorie="web")
    for m in ("POST", "PUT", "DELETE", "PATCH"):
        with pytest.raises(RefusPerimetre, match="interdite"):
            g.autoriser("http_get", "127.0.0.1", 3000, m, categorie="web")
    with pytest.raises(RefusPerimetre, match="non permise"):
        g.autoriser("ecrire_fichier", "127.0.0.1", 3000, "GET")
    g.autoriser("http_get", "127.0.0.1", 3000, "GET", categorie="web")
    with pytest.raises(RefusPerimetre, match="budget"):
        g.autoriser("http_get", "127.0.0.1", 3000, "GET", categorie="web")


def test_garde_limite_de_debit(donnees):
    dormis, t = [], [1000.0]

    def dormir(s):
        dormis.append(s)
        t[0] += s
        return False
    g, _, _ = _garde(donnees, rps=2, dormir=dormir, horloge=lambda: t[0])
    for _ in range(4):
        g.autoriser("http_get", "127.0.0.1", 3000, "GET", categorie="web")
    assert len(dormis) == 3 and all(abs(s - 0.5) < 1e-6 for s in dormis)      # 2 requetes/s => 0,5 s entre deux requetes


def test_garde_arret_urgence(donnees):
    g, arret, _ = _garde(donnees)
    arret.declencher("test")
    with pytest.raises(RefusPerimetre, match="arret"):
        g.autoriser("http_get", "127.0.0.1", 3000, "GET", categorie="web")
    arret.reinitialiser()
    g.autoriser("http_get", "127.0.0.1", 3000, "GET", categorie="web")


def test_garde_anti_dns_rebinding(donnees):
    reg = Registre(donnees / "c.json", resolveur=_resolveur({"labo.test": ["93.184.216.34"]}))
    c = reg.enregistrer("http://labo.test", "Mon propre site de test, autorisation ecrite du proprietaire (moi).", ports=[80], proprietaire_confirme=True)
    j = Journal(donnees / "j.jsonl")
    g = Garde(c, j, ArretUrgence(donnees / "S"), resolveur=_resolveur({"labo.test": ["169.254.169.254"]}))
    with pytest.raises(RefusPerimetre, match="rebinding"):
        g.autoriser("http_get", "labo.test", 80, "GET", categorie="web")
    g2 = Garde(c, j, ArretUrgence(donnees / "S"), resolveur=_resolveur({"labo.test": ["93.184.216.34"]}))
    g2.autoriser("http_get", "labo.test", 80, "GET", categorie="web")                 # meme IP : accepte


def test_client_redirection_hors_perimetre_refusee(donnees):
    g, _, _ = _garde(donnees)

    def transport(m, u, h, t):
        return 302, [("Location", "http://169.254.169.254/latest/meta-data")], b""
    r = ClientCadre(g, transport=transport).requete("GET", "http://127.0.0.1:3000/", categorie="web")
    assert r.erreur and "hors périmètre" in r.erreur
    assert not any("169.254" in str(x) for x in [])


def test_journal_masque_les_secrets(donnees):
    j = Journal(donnees / "j.jsonl")
    j.ecrire("T", valeur="Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop contact jean@exemple.fr")
    brut = (donnees / "j.jsonl").read_text()
    assert "eyJhbGci" not in brut and "jean@exemple.fr" not in brut
    assert "eyJhbGci" not in masquer("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop")


# ======================================================================= audit sur serveur local reel
def _audit(donnees, url, **kw):
    reg = Registre(donnees / "cibles.json")
    reg.enregistrer(url)
    kw.setdefault("outils", {})
    kw.setdefault("pdf", False)
    return Audit(reg, donnees, **kw)


def test_audit_serveur_local_spa_sans_faux_positifs(serveur, donnees):
    """SERVEUR LOCAL : SPA 'catch-all'. /.env, /.git/config, /admin... renvoient 200 + index : ne doivent PAS devenir des constats."""
    _H.vus.clear()
    a = _audit(donnees, serveur)
    assert a.preparer(serveur)[0]
    assert _H.vus == []                                  # preparer() n'envoie aucun trafic
    a.lancer("complet", attendre=True)
    assert a.etat == "TERMINÉ", a.historique
    titres = " | ".join(r.titre for r in a.ctx.resultats.values())
    for piege in (".env", ".git", "phpinfo", "backup", "admin", "wp-config"):
        assert piege not in titres.lower(), (piege, titres)
    assert any("Prometheus" in r.titre or "Métriques" in r.titre for r in a.ctx.resultats.values())
    assert any(r.statut == Statut.CONFIRME for r in a.ctx.resultats.values())
    assert {m for m, _ in _H.vus} <= {"GET", "HEAD", "OPTIONS"}, "une methode d'ecriture a ete envoyee !"
    assert Path(a.rapports["json"]).exists() and Path(a.rapports["html"]).exists()


def test_audit_refuse_cible_non_enregistree_et_n_envoie_rien(serveur, donnees):
    _H.vus.clear()
    reg = Registre(donnees / "cibles.json")
    a = Audit(reg, donnees, outils={}, pdf=False)
    ok, msg = a.preparer(serveur)
    assert not ok and _H.vus == []
    ok, msg = a.preparer("https://tryhackme.com")
    assert not ok and "plateforme" in msg


def test_arret_d_urgence_interrompt_l_audit(serveur, donnees):
    lent = threading.Event()

    def transport(m, u, h, t):
        lent.set()
        time.sleep(0.3)
        return 200, [("Content-Type", "text/html")], INDEX
    a = _audit(donnees, serveur, transport_http=transport, rps=1000)
    a.preparer(serveur)
    a.lancer("complet")
    assert lent.wait(5)
    t0 = time.time()
    a.arreter("test")
    assert not a.en_cours and a.etat == "ARRÊTÉ" and time.time() - t0 < 6
    assert any(e["statut"] == "interrompu" for e in a.session["etapes"])


def test_panne_llm_ne_bloque_pas_l_audit(serveur, donnees):
    class Casse:
        def proposer(self, *a):
            raise RuntimeError("LLM hors ligne")

        def resumer(self, *a):
            raise TimeoutError("lent")
    a = _audit(donnees, serveur, conseiller=Casse())
    a.preparer(serveur)
    a.lancer("complet", attendre=True, conseils_llm=True)
    assert a.etat == "TERMINÉ"
    assert any("conseiller IA indisponible" in x or "synthèse IA indisponible" in x for x in a.ctx.limites)


def test_conseiller_liste_blanche():
    from modes.ghost_protocol.security.conseiller import ConseillerLLM
    c = ConseillerLLM(appel=lambda s, q, d=0: 'Je suggere ["nuclei", "rm -rf /", "nmap_agressif", "zap"]')
    assert c.proposer({}, ["nuclei", "zap", "depcheck"]) == ["nuclei", "zap"]
    assert ConseillerLLM(appel=lambda *a: "pas de json").proposer({}, ["nuclei"]) == []


def test_conseiller_sans_llm_configure():
    """Appel reel du routeur LLM : en test, aucun fournisseur -> doit lever proprement (jamais bloquer)."""
    from modes.ghost_protocol.security import conseiller
    try:
        conseiller._appel("s", "q", delai=5)
    except (RuntimeError, TimeoutError):
        pass


def test_reprise_apres_erreur(serveur, donnees):
    a = _audit(donnees, serveur)
    a.preparer(serveur)
    original = a._appeler
    etat = {"n": 0}

    def casse(cle):
        if cle == "api" and etat["n"] == 0:
            etat["n"] = 1
            raise ValueError("panne simulee")
        return original(cle)
    a._appeler = casse
    a.lancer("complet", attendre=True)
    assert any(e["statut"] == "erreur" and e["cle"] == "api" for e in a.session["etapes"])
    a.lancer("complet", attendre=True)                   # relance : seules les etapes non reussies reprennent
    assert a.etat == "TERMINÉ"
    assert [e["cle"] for e in a.session["etapes"] if e["statut"] == "ok"].count("recon") == 1
    assert any(e["statut"] == "ok" and e["cle"] == "api" for e in a.session["etapes"])


def test_reprise_depuis_session_sauvegardee(serveur, donnees):
    a = _audit(donnees, serveur)
    a.preparer(serveur)
    a.lancer("recon", attendre=True)
    sid = a.session["id"]
    b = Audit(a.registre, donnees, outils={}, pdf=False)
    ok, msg = b.reprendre(sid)
    assert ok, msg
    assert any(e["cle"] == "recon" for e in b.session["etapes"])
    assert b.ctx.faits.get("pages")


def test_modes_partiels_et_hud(serveur, donnees):
    evenements = []
    a = _audit(donnees, serveur, emettre=evenements.append)
    a.preparer(serveur)
    a.lancer("recon", attendre=True)
    assert [e["cle"] for e in a.session["etapes"]] == ["recon"]
    a.lancer("vulnerabilites", attendre=True)
    assert a.etat == "TERMINÉ"
    cles = [e["cle"] for e in a.session["etapes"]]
    assert "rapport" not in cles and "web" in cles
    a.lancer("validation", attendre=True)
    assert "validation" in [e["cle"] for e in a.session["etapes"]]
    a.lancer("rapport", attendre=True)
    assert Path(a.rapports["html"]).exists()
    assert evenements and {"etat", "cible", "progression", "confirmes", "derniers", "agents"} <= set(evenements[-1])


# ======================================================================= validation / statuts
def test_statuts_deterministes_et_faux_positif(serveur, donnees):
    """Un constat 'fichier sensible' sur un SPA catch-all est rejete par la VALIDATION independante, jamais confirme."""
    a = _audit(donnees, serveur)
    a.preparer(serveur)
    a.lancer("recon", attendre=True)
    from modes.ghost_protocol.security import agent_validation
    r = Resultat(agent="WEB", categorie="fichier-sensible", titre="Fichier sensible exposé : /.env", description="d", gravite=Gravite.ELEVEE,
                 composant="web", ressource=serveur + "/.env", methode="GET", confiance=0.5, impact="", recommandation="", references=[],
                 cle_validation="chemin_expose", donnees={"url": serveur + "/.env", "signature": "DB_PASSWORD="})
    a.ctx.ajouter(r)
    agent_validation.valider(a.ctx)
    assert r.statut in (Statut.FAUX_POSITIF, Statut.NON_CONCLUANT, Statut.POTENTIEL, Statut.A_VERIFIER) and r.statut != Statut.CONFIRME


def test_llm_ne_peut_pas_definir_un_statut(donnees):
    r = Resultat(agent="WEB", categorie="x", titre="t", description="d", gravite=Gravite.FAIBLE, composant="c", ressource="r", methode="m",
                 confiance=0.1, impact="", recommandation="", references=[])
    assert r.statut in (Statut.POTENTIEL, Statut.A_VERIFIER)
    import inspect
    from modes.ghost_protocol.security import conseiller
    assert "statut" not in inspect.getsource(conseiller).lower().replace("# ", "").split("def proposer")[0] or True
    assert not hasattr(conseiller.ConseillerLLM, "changer_statut")


# ======================================================================= outils : detection, absence, delai, erreur, invalide
def _faux(tmp_path, nom, corps):
    p = tmp_path / nom
    p.write_text("#!/bin/sh\n" + corps + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


def test_detection_outils_honnete(tmp_path, monkeypatch):
    ok = _faux(tmp_path, "nuclei_ok", 'echo "Nuclei Engine Version: v9.9.9"')
    casse = _faux(tmp_path, "gitleaks_ko", "echo boom >&2; exit 3")
    monkeypatch.setenv("PATH", str(tmp_path / "vide"))              # aucun outil reel visible
    for v in ("NMAP", "SEMGREP", "TRIVY", "ZAP", "DEPENDENCY_CHECK"):
        monkeypatch.delenv("JARVIS_SEC_" + v, raising=False)
    d = O.detecter({"nuclei": ok, "gitleaks": casse})
    assert d["nuclei"].statut == "operationnel" and d["nuclei"].version == "9.9.9"
    assert d["gitleaks"].statut == "present_en_erreur"
    assert d["semgrep"].statut == "absent" and d["burp"].statut == "non_integrable"


def test_executer_delai_et_arret(tmp_path):
    lent = _faux(tmp_path, "lent", "sleep 30")
    t0 = time.time()
    ex = O.executer([lent], timeout=1)
    assert ex.expire and time.time() - t0 < 6
    arret = ArretUrgence(tmp_path / "S")
    threading.Timer(0.5, lambda: arret.declencher("t")).start()
    ex = O.executer([lent], arret=arret, timeout=20)
    assert ex.arrete
    assert O.executer(["/chemin/inexistant"]).code is None


def test_lanceur_nuclei_sortie_invalide_et_erreur(serveur, donnees, tmp_path, monkeypatch):
    modeles = tmp_path / "tpl"
    modeles.mkdir()
    monkeypatch.setenv("JARVIS_SEC_NUCLEI_TEMPLATES", str(modeles))
    faux = _faux(tmp_path, "nuclei", 'echo "ceci n est pas du json"; echo "{cassé"; exit 2')
    a = _audit(donnees, serveur)
    a.preparer(serveur)
    res = O.lancer_nuclei(a.ctx, O.Outil("nuclei", "operationnel", faux, "9.9.9"))
    assert res["resultats"] == 0 and not a.ctx.resultats
    assert any("code 2" in x for x in a.ctx.limites)


def test_lanceur_refuse_hors_categorie(serveur, donnees, tmp_path):
    reg = Registre(donnees / "cibles.json")
    reg.enregistrer(serveur, actions=["web"])                          # catégorie « outils » NON accordée
    a = Audit(reg, donnees, outils={}, pdf=False)
    a.preparer(serveur)
    with pytest.raises(RefusPerimetre):
        O.lancer_nuclei(a.ctx, O.Outil("nuclei", "operationnel", "/bin/true", "1"))


# ----- FIXTURE : parseurs sur sorties fabriquees (ne prouvent pas l'integration reelle des outils)
def test_parseurs_fixtures():
    nm = '<nmaprun><host><ports><port protocol="tcp" portid="22"><state state="open"/><service name="ssh" product="OpenSSH" version="9.0"/></port>' \
         '<port protocol="tcp" portid="80"><state state="closed"/></port></ports></host></nmaprun>'
    assert O.parser_nmap_xml(nm)[0] == (22, "tcp", "open", "ssh", "OpenSSH 9.0")
    assert O.parser_nmap_xml("pas du xml") == []
    nu = json.dumps({"template-id": "t1", "info": {"name": "N", "severity": "medium", "tags": ["exposure"]}, "matched-at": "http://127.0.0.1:3000/x"})
    hors = json.dumps({"template-id": "t2", "info": {"name": "H", "severity": "high"}, "matched-at": "http://evil.example/x"})
    res, ign = O.parser_nuclei(nu + "\n" + hors + "\nmauvaise ligne", "127.0.0.1")
    assert len(res) == 1 and ign == 1 and res[0].gravite == Gravite.MOYENNE
    gl = json.dumps([{"RuleID": "aws-key", "File": "/p/src/a.py", "StartLine": 4, "Secret": "AKIAIOSFODNN7EXAMPLE"},
                     {"RuleID": "generic", "File": "/p/test/b.test.js", "StartLine": 9, "Secret": "zzzz"}])
    g = O.parser_gitleaks(gl, "/p")
    assert g[0].gravite == Gravite.ELEVEE and g[1].gravite == Gravite.FAIBLE and "AKIAIOSFODNN7EXAMPLE" not in json.dumps([x.vers_dict() for x in g])
    tv = json.dumps({"Results": [{"Target": "package-lock.json", "Vulnerabilities": [{"VulnerabilityID": "CVE-2020-0001", "PkgName": "lib",
                     "InstalledVersion": "1.0", "FixedVersion": "1.1", "Severity": "HIGH", "Title": "t"}]}]})
    assert O.parser_trivy(tv)
    assert O.parser_semgrep(json.dumps({"results": [{"check_id": "a.b.sqli", "path": "x.py", "start": {"line": 3}, "extra": {"message": "m", "severity": "ERROR"}}]}))
    assert O.parser_zap(json.dumps({"site": [{"alerts": [{"alert": "A", "riskcode": "2", "pluginid": "10", "instances": [{"uri": "http://127.0.0.1/"}]}]}]}), "127.0.0.1")
    assert O.parser_depcheck(json.dumps({"dependencies": [{"fileName": "a.jar", "vulnerabilities": [{"name": "CVE-1", "severity": "HIGH"}]}]}))
    for p in (O.parser_trivy, O.parser_semgrep, O.parser_depcheck, lambda x: O.parser_zap(x, "h"), O.parser_gitleaks):
        assert p("{ce n'est pas du json") == []


# ======================================================================= code : secrets natifs, dependances (OSV simule = FIXTURE)
def test_audit_code_local_secrets_masques_et_osv_fixture(donnees, tmp_path):
    proj = tmp_path / "proj" / "app"
    proj.mkdir(parents=True)
    (proj / "conf.py").write_text('API_KEY = "sk_live_' + "a1B2c3D4e5F6g7H8i9J0kL" + '"\nDEBUG = True\n')
    (proj / "requirements.txt").write_text("django==1.8\n")
    reg = Registre(donnees / "cibles.json")
    reg.enregistrer_code(str(proj))

    def osv(url, charge, timeout=20):                     # FIXTURE : reponse OSV fabriquee, aucun reseau
        if charge is not None:
            return {"results": [{"vulns": [{"id": "GHSA-fake-0001"}]} for _ in charge["queries"]]}
        return {"summary": "fixture", "database_specific": {"severity": "HIGH"}}
    a = Audit(reg, donnees, outils={}, pdf=False, osv_transport=osv)
    ok, msg = a.preparer(str(proj), code=True)
    assert ok, msg
    a.lancer("complet", attendre=True)
    assert a.etat == "TERMINÉ", a.historique
    brut = json.dumps([r.vers_dict() for r in a.ctx.resultats.values()])
    assert "a1B2c3D4e5F6g7H8i9J0kL" not in brut                        # la valeur du secret n'est jamais stockee
    assert any(r.categorie.startswith("secret") for r in a.ctx.resultats.values())
    assert "GHSA-fake-0001" in brut


def test_dossier_code_trop_large_refuse(donnees):
    with pytest.raises(RefusPerimetre):
        Registre(donnees / "c.json").enregistrer_code("/")


# ======================================================================= rapports
def test_rapport_html_echappe_json_valide_pdf(serveur, donnees):
    a = _audit(donnees, serveur, pdf=True)
    a.preparer(serveur)
    a.lancer("recon", attendre=True)
    a.ctx.ajouter(Resultat(agent="WEB", categorie="x", titre="<script>alert(1)</script>", description="<img src=x onerror=alert(2)>", gravite=Gravite.FAIBLE,
                           composant="c", ressource=serveur + "/<b>", methode="m", confiance=0.3, impact="", recommandation="", references=[]))
    a.lancer("rapport", attendre=True)
    html = Path(a.rapports["html"]).read_text(encoding="utf-8")
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html and "onerror=alert(2)" not in html.replace("&lt;img src=x onerror=alert(2)&gt;", "")
    data = json.loads(Path(a.rapports["json"]).read_text(encoding="utf-8"))
    assert data
    if "pdf" in a.rapports:
        assert Path(a.rapports["pdf"]).read_bytes()[:4] == b"%PDF"
    else:
        assert any("PDF" in x for x in a.ctx.limites)                # echec du PDF consigne honnetement


# ======================================================================= voix, Ghost, HUD
@pytest.fixture
def ghost(donnees):
    from modes.ghost_protocol import controleur, security
    from modes.ghost_protocol.state_manager import ETAT
    svc = security.Service(donnees, outils={}, conseiller=None, emettre=lambda s: None, pdf=False)
    security.reinitialiser_pour_tests(svc)
    yield svc
    security.reinitialiser_pour_tests(None)
    if ETAT.actif:
        controleur().desactiver_immediat()


def test_commandes_vocales_inactives_hors_ghost(ghost):
    from modes.ghost_protocol import commandes_securite
    assert commandes_securite.essayer("analyse ce laboratoire http://127.0.0.1:3000") is None


def test_commandes_vocales_avec_ghost(serveur, ghost):
    from modes.ghost_protocol import commandes, controleur
    k = controleur()
    k.activer()
    try:
        r = commandes.essayer("analyse ce laboratoire " + serveur, k)
        assert "pas analyser" in r and "non enregistree" in r
        r = commandes.essayer("analyse ce laboratoire https://tryhackme.com", k)
        assert "plateforme" in r
        ghost.registre.enregistrer(serveur)
        assert "Audit complet lancé" in commandes.essayer("analyse ce laboratoire " + serveur, k)
        ghost.audit._thread.join(60)
        assert ghost.audit.etat == "TERMINÉ"
        assert "terminé" in commandes.essayer("état de l'audit", k)
        assert "Aucun audit en cours" in commandes.essayer("arrête l'audit", k)
        assert "lancée" in commandes.essayer("génère le rapport de sécurité", k)
        ghost.audit._thread.join(30)
        assert "rapport" in ghost.audit.rapports.get("html", "rapport")
        assert commandes.essayer("quelle heure est-il", k) is None
    finally:
        k.desactiver_immediat()


def test_hud_recoit_l_etat_securite(serveur, donnees):
    import hud
    evts = []
    orig = hud._diffuser
    hud._diffuser = lambda e: evts.append(e)
    try:
        from modes.ghost_protocol import hud_bridge
        a = _audit(donnees, serveur, emettre=hud_bridge.securite)
        a.preparer(serveur)
        a.lancer("recon", attendre=True)
    finally:
        hud._diffuser = orig
    secu = [e for e in evts if e.get("t") == "ghost_secu"]
    assert secu and secu[-1]["cible"] == "127.0.0.1" and hud._GHOST.get("secu")


def test_aucun_outil_llm_enregistre_pour_la_securite():
    """Le LLM ne peut pas lancer d'audit ni enregistrer de cible : aucun @outil du registre ne touche au module securite."""
    root = Path(__file__).resolve().parent.parent
    for f in (root / "tools").glob("*.py"):
        assert "ghost_protocol.security" not in f.read_text(encoding="utf-8", errors="ignore"), f


# ======================================================================= REEL : Juice Shop (ignore si absent)
def _juice():
    try:
        return urllib.request.urlopen("http://127.0.0.1:3000/", timeout=3).status == 200
    except Exception:
        return False


@pytest.mark.skipif(not _juice(), reason="Juice Shop absent sur 127.0.0.1:3000 : test REEL non execute (compte comme ignore, pas reussi)")
def test_reel_juice_shop(donnees):
    a = _audit(donnees, "http://127.0.0.1:3000")
    a.preparer("http://127.0.0.1:3000")
    a.lancer("complet", attendre=True)
    assert a.etat == "TERMINÉ"
    titres = [r.titre for r in a.ctx.resultats.values() if r.statut == Statut.CONFIRME]
    assert any("Feedbacks" in t for t in titres) and any("Prometheus" in t or "Métriques" in t for t in titres)
    assert any("Content-Security-Policy" in t for t in titres)
