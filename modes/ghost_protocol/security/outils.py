"""Outils de securite externes : detection reelle (chemin, version), execution encadree et lecture des sorties structurees.

Un outil n'est declare « operationnel » que si sa commande de version s'execute VRAIMENT (code 0) ; sinon « absent » ou
« present_en_erreur ». Burp Suite Community n'offre aucune interface d'automatisation : « non_integrable ». Les commandes sont
construites a partir de listes blanches d'options (jamais de shell, jamais de texte libre), avec delai maximal et arret d'urgence.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from modes.ghost_protocol.security.modele import Gravite, Preuve, Resultat, masquer

CANDIDATS = {
    "nmap": (["nmap"], [r"C:\Program Files (x86)\Nmap\nmap.exe", r"C:\Program Files\Nmap\nmap.exe"], ["--version"]),
    "nuclei": (["nuclei"], [os.path.expanduser(r"~\go\bin\nuclei.exe"), os.path.expanduser("~/go/bin/nuclei")], ["-version"]),
    "semgrep": (["semgrep"], [], ["--version"]),
    "gitleaks": (["gitleaks"], [], ["version"]),
    "trivy": (["trivy"], [r"C:\Program Files\trivy\trivy.exe"], ["--version"]),
    "dependency-check": (["dependency-check.bat", "dependency-check.sh", "dependency-check"], [], ["--version"]),
    "zap": (["zap-baseline.py", "zap.sh", "zap.bat"], [r"C:\Program Files\ZAP\Zed Attack Proxy\zap.bat"], ["-version"]),
}
DOC = {"nmap": "https://nmap.org/book/man.html", "nuclei": "https://docs.projectdiscovery.io/tools/nuclei/overview",
       "semgrep": "https://semgrep.dev/docs/", "gitleaks": "https://github.com/gitleaks/gitleaks", "trivy": "https://trivy.dev/latest/",
       "dependency-check": "https://owasp.org/www-project-dependency-check/", "zap": "https://www.zaproxy.org/docs/"}


@dataclass
class Outil:
    nom: str
    statut: str            # operationnel | absent | present_en_erreur | non_integrable
    chemin: str = ""
    version: str = ""
    note: str = ""
    valide_en_reel: bool = False      # rempli par les tests/rapports : l'outil a-t-il ete execute pour de vrai pendant cet audit ?

    def vers_dict(self):
        return self.__dict__.copy()


@dataclass
class Execution:
    code: int | None
    sortie: str
    erreur: str
    expire: bool = False
    arrete: bool = False
    duree: float = 0.0


def _env_sain() -> dict:
    try:
        from core.missions import environnement_sain
        env = environnement_sain()
    except Exception:
        env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG")}
    for k in ("HOME", "USERPROFILE", "PATH", "SYSTEMROOT", "TEMP", "TMP"):
        if k in os.environ:
            env.setdefault(k, os.environ[k])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def executer(cmd: list, arret=None, timeout: float = 300, cwd=None, max_sortie: int = 4_000_000) -> Execution:
    """Lance cmd (liste, jamais de shell), lit stdout/stderr sans blocage, tue au delai ou a l'arret d'urgence."""
    debut = time.time()
    kw = {"start_new_session": True} if os.name != "nt" else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, cwd=cwd,
                             env=_env_sain(), **kw)
    except (OSError, ValueError) as e:
        return Execution(None, "", f"{type(e).__name__}: {e}", duree=time.time() - debut)
    tampons = {"o": [], "e": []}

    def lire(flux, cle):
        total = 0
        for bloc in iter(lambda: flux.read(65536), b""):
            total += len(bloc)
            if total <= max_sortie:
                tampons[cle].append(bloc)
    fils = [threading.Thread(target=lire, args=(p.stdout, "o"), daemon=True), threading.Thread(target=lire, args=(p.stderr, "e"), daemon=True)]
    for f in fils:
        f.start()
    expire = arrete = False
    while p.poll() is None:
        if arret is not None and arret.actif():
            arrete = True
        elif time.time() - debut > timeout:
            expire = True
        if arrete or expire:
            try:
                os.killpg(p.pid, signal.SIGKILL) if os.name != "nt" else p.kill()
            except (OSError, ProcessLookupError):
                p.kill()
            break
        time.sleep(0.1)
    p.wait()
    for f in fils:
        f.join(2)
    return Execution(p.returncode, b"".join(tampons["o"]).decode("utf-8", "replace"), b"".join(tampons["e"]).decode("utf-8", "replace"),
                     expire, arrete, time.time() - debut)


def detecter(surcharges: dict | None = None) -> dict:
    """Etat REEL de chaque outil : trouve ? execute ? quelle version ?"""
    surcharges = surcharges or {}
    out = {}
    for nom, (noms, chemins, verif) in CANDIDATS.items():
        chemin = surcharges.get(nom) or os.environ.get("JARVIS_SEC_" + nom.upper().replace("-", "_"), "")
        if not chemin:
            chemin = next((shutil.which(n) for n in noms if shutil.which(n)), "") or next((c for c in chemins if os.path.isfile(c)), "")
        if not chemin:
            out[nom] = Outil(nom, "absent", note=f"non trouvé dans le PATH ni aux emplacements usuels ; documentation : {DOC[nom]}")
            continue
        ex = executer([chemin] + verif, timeout=45)
        sortie = (ex.sortie + "\n" + ex.erreur).strip()
        m = re.search(r"\d+\.\d+(?:\.\d+)?", sortie)
        if ex.code == 0 and m:
            out[nom] = Outil(nom, "operationnel", chemin, m.group(0), "version obtenue par exécution réelle")
        else:
            out[nom] = Outil(nom, "present_en_erreur", chemin, "", f"la commande de version a échoué (code {ex.code}) : {sortie[:120]}")
    out["burp"] = Outil("burp", "non_integrable", note="Burp Suite Community n'expose aucune API/CLI d'automatisation : utilisable seulement "
                        "manuellement. Non intégré (https://portswigger.net/burp/documentation).")
    return out


# ------------------------------------------------------------------ parseurs de sorties structurees (fonctions pures)
GRAV = {"info": Gravite.INFO, "informational": Gravite.INFO, "low": Gravite.FAIBLE, "medium": Gravite.MOYENNE, "moderate": Gravite.MOYENNE,
        "high": Gravite.ELEVEE, "critical": Gravite.CRITIQUE, "unknown": Gravite.INFO, "warning": Gravite.MOYENNE, "error": Gravite.ELEVEE}


def _grav(s) -> Gravite:
    return GRAV.get(str(s or "").lower(), Gravite.INFO)


def parser_nmap_xml(xml: str) -> list:
    """[(port, protocole, etat, service, produit/version)]"""
    ports = []
    try:
        racine = ET.fromstring(xml)
    except ET.ParseError:
        return []
    for p in racine.iter("port"):
        etat = p.find("state")
        svc = p.find("service")
        ports.append((int(p.get("portid", 0)), p.get("protocol", "tcp"), etat.get("state") if etat is not None else "?",
                      svc.get("name", "") if svc is not None else "",
                      " ".join(x for x in ((svc.get("product", ""), svc.get("version", "")) if svc is not None else ()) if x)))
    return ports


def parser_nuclei(jsonl: str, hote: str) -> tuple:
    """(resultats, ignores_hors_perimetre)"""
    out, hors = [], 0
    for ligne in jsonl.splitlines():
        try:
            d = json.loads(ligne)
        except ValueError:
            continue
        loc = str(d.get("matched-at") or d.get("host") or "")
        h = re.sub(r"^[a-z]+://", "", loc).split("/")[0].rsplit(":", 1)[0].strip("[]").lower()
        if h != hote:
            hors += 1
            continue
        info = d.get("info", {}) or {}
        cls = info.get("classification", {}) or {}
        refs = [str(x) for x in (cls.get("cwe-id") or [])] + [str(x) for x in (cls.get("cve-id") or [])]
        out.append(Resultat(agent="OUTIL:nuclei", categorie="nuclei:" + ",".join(info.get("tags", [])[:3] if isinstance(info.get("tags"), list) else [str(info.get("tags", ""))[:30]]),
                            titre=str(info.get("name", d.get("template-id", "?")))[:140], description=str(info.get("description", ""))[:400] or str(info.get("name", "")),
                            gravite=_grav(info.get("severity")), composant="détection nuclei", ressource=loc, methode=f"nuclei template {d.get('template-id', '?')}",
                            confiance=0.7, impact=str(info.get("impact", ""))[:200], recommandation=str(info.get("remediation", "Corriger la configuration signalée."))[:300],
                            references=[r.upper() if r.lower().startswith(("cwe", "cve")) else r for r in refs], cle_validation="nuclei",
                            donnees={"template": d.get("template-id", ""), "url": loc},
                            preuves=[Preuve(f"nuclei {d.get('template-id', '?')}", None, masquer(str(d.get("extracted-results") or d.get("matcher-name") or "correspondance du modèle")))]))
    return out, hors


def parser_gitleaks(rapport: str, racine: str = "") -> list:
    try:
        liste = json.loads(rapport or "[]") or []
    except ValueError:
        return []
    out = []
    for d in liste:
        f = str(d.get("File", ""))
        rel = f[len(racine):].lstrip("/\\") if racine and f.startswith(racine) else f
        en_test = bool(re.search(r"(^|[/\\])(tests?|specs?|__tests__|fixtures?|mocks?|examples?)([/\\]|$)|\.(test|spec)\.", rel, re.I))
        out.append(Resultat(agent="OUTIL:gitleaks", categorie="secret-expose",
                            titre=f"Secret potentiel ({d.get('RuleID', '?')}) dans {rel}:{d.get('StartLine', '?')}" + (" [fichier de test]" if en_test else ""),
                            description=str(d.get("Description", "secret détecté"))[:200], gravite=Gravite.FAIBLE if en_test else Gravite.ELEVEE, composant="code source",
                            ressource=f"{rel}:{d.get('StartLine', '?')}", methode="gitleaks (regex + entropie)", confiance=0.6,
                            impact="Un secret versionné peut être réutilisé par quiconque accède au dépôt.",
                            recommandation="Révoquer/renouveler le secret, le retirer de l'historique, utiliser un gestionnaire de secrets.",
                            references=["CWE-798"], cle_validation="secret_fichier",
                            donnees={"fichier": rel, "ligne": d.get("StartLine"), "regle": d.get("RuleID", ""), "entropie": d.get("Entropy")},
                            preuves=[Preuve(f"gitleaks {d.get('RuleID', '')}", None, f"{rel}:{d.get('StartLine')} (valeur masquée par l'outil, non testée)")]))
    return out


def parser_trivy(rapport: str) -> list:
    try:
        d = json.loads(rapport or "{}")
    except ValueError:
        return []
    out = []
    for res in d.get("Results", []) or []:
        cible = res.get("Target", "")
        for v in res.get("Vulnerabilities", []) or []:
            out.append(Resultat(agent="OUTIL:trivy", categorie="dependance-vulnerable", titre=f"{v.get('VulnerabilityID', '?')} dans {v.get('PkgName', '?')} {v.get('InstalledVersion', '')}",
                                description=str(v.get("Title") or v.get("Description", ""))[:300], gravite=_grav(v.get("Severity")), composant=f"{v.get('PkgName', '?')} {v.get('InstalledVersion', '')}",
                                ressource=cible, methode="trivy (base de vulnérabilités)", confiance=0.8,
                                impact="La version installée est affectée ; l'exploitabilité dépend de l'usage dans l'application.",
                                recommandation=f"Mettre à jour vers {v.get('FixedVersion') or 'une version corrigée'}.",
                                references=[v.get("VulnerabilityID", "")] + [str(c) for c in (v.get("CweIDs") or [])][:2], cle_validation="dependance",
                                donnees={"paquet": v.get("PkgName"), "version": v.get("InstalledVersion"), "id": v.get("VulnerabilityID")},
                                preuves=[Preuve("trivy fs", None, f"{v.get('PkgName')} {v.get('InstalledVersion')} -> {v.get('VulnerabilityID')}")]))
        for s in res.get("Secrets", []) or []:
            out.append(Resultat(agent="OUTIL:trivy", categorie="secret-expose", titre=f"Secret potentiel ({s.get('RuleID', '?')}) dans {cible}",
                                description=str(s.get("Title", "secret détecté")), gravite=_grav(s.get("Severity") or "high"), composant="code source",
                                ressource=f"{cible}:{s.get('StartLine', '?')}", methode="trivy secret scanning", confiance=0.6,
                                impact="Un secret versionné peut être réutilisé.", recommandation="Révoquer et retirer le secret.", references=["CWE-798"],
                                cle_validation="secret_fichier", donnees={"fichier": cible, "ligne": s.get("StartLine"), "regle": s.get("RuleID", "")},
                                preuves=[Preuve("trivy secret", None, f"{cible}:{s.get('StartLine')} (valeur non conservée)")]))
        for m in res.get("Misconfigurations", []) or []:
            out.append(Resultat(agent="OUTIL:trivy", categorie="mauvaise-configuration", titre=str(m.get("Title", m.get("ID", "?")))[:140],
                                description=str(m.get("Description", ""))[:300], gravite=_grav(m.get("Severity")), composant="configuration",
                                ressource=cible, methode="trivy misconfig", confiance=0.7, impact=str(m.get("Message", ""))[:200],
                                recommandation=str(m.get("Resolution", ""))[:300], references=[m.get("ID", "")], cle_validation="outil_seul",
                                donnees={"id": m.get("ID")}))
    return out


def parser_semgrep(rapport: str) -> list:
    try:
        d = json.loads(rapport or "{}")
    except ValueError:
        return []
    out = []
    for r in d.get("results", []) or []:
        extra = r.get("extra", {}) or {}
        meta = extra.get("metadata", {}) or {}
        cwe = meta.get("cwe") or []
        cwe = [cwe] if isinstance(cwe, str) else cwe
        out.append(Resultat(agent="OUTIL:semgrep", categorie="code-vulnerable", titre=str(r.get("check_id", "?")).rsplit(".", 1)[-1][:100],
                            description=str(extra.get("message", ""))[:300], gravite=_grav(extra.get("severity")), composant="code source",
                            ressource=f"{r.get('path', '?')}:{(r.get('start') or {}).get('line', '?')}", methode=f"semgrep règle {r.get('check_id', '?')}",
                            confiance=0.5, impact="Motif de code associé à une vulnérabilité (à confirmer par revue).",
                            recommandation=str(meta.get("fix") or "Revoir ce code selon la règle."), references=[str(c).split(":")[0] for c in cwe][:2],
                            cle_validation="outil_seul", donnees={"regle": r.get("check_id")}))
    return out


def parser_zap(rapport: str, hote: str) -> list:
    try:
        d = json.loads(rapport or "{}")
    except ValueError:
        return []
    out = []
    for site in d.get("site", []) or []:
        for a in site.get("alerts", []) or []:
            sev = {"3": "high", "2": "medium", "1": "low", "0": "info"}.get(str(a.get("riskcode")), "info")
            urls = [i.get("uri", "") for i in a.get("instances", [])][:3]
            out.append(Resultat(agent="OUTIL:zap", categorie="zap:" + str(a.get("pluginid", "")), titre=str(a.get("alert", a.get("name", "?")))[:140],
                                description=re.sub(r"<[^>]+>", "", str(a.get("desc", "")))[:300], gravite=_grav(sev), composant="détection ZAP (passive)",
                                ressource=urls[0] if urls else hote, methode="OWASP ZAP baseline (passif)", confiance=0.6,
                                impact="", recommandation=re.sub(r"<[^>]+>", "", str(a.get("solution", "")))[:300],
                                references=[f"CWE-{a['cweid']}"] if str(a.get("cweid", "-1")) not in ("-1", "0", "") else [], cle_validation="outil_seul",
                                donnees={"plugin": a.get("pluginid")}))
    return out


def parser_depcheck(rapport: str) -> list:
    try:
        d = json.loads(rapport or "{}")
    except ValueError:
        return []
    out = []
    for dep in d.get("dependencies", []) or []:
        for v in dep.get("vulnerabilities", []) or []:
            out.append(Resultat(agent="OUTIL:dependency-check", categorie="dependance-vulnerable", titre=f"{v.get('name', '?')} dans {dep.get('fileName', '?')}",
                                description=str(v.get("description", ""))[:300], gravite=_grav(v.get("severity")), composant=str(dep.get("fileName", "?")),
                                ressource=str(dep.get("filePath", "")), methode="OWASP Dependency-Check (NVD)", confiance=0.6,
                                impact="Composant référencé comme vulnérable (faux positifs d'identification fréquents).",
                                recommandation="Mettre à jour le composant.", references=[v.get("name", "")] + [str(c) for c in (v.get("cwes") or [])][:1],
                                cle_validation="outil_seul", donnees={"id": v.get("name")}))
    return out


# ------------------------------------------------------------------ lanceurs (un par outil, options en liste blanche)
def _templates_nuclei() -> str:
    for c in (os.environ.get("JARVIS_SEC_NUCLEI_TEMPLATES", ""), os.path.expanduser("~/nuclei-templates"), os.path.expanduser("~/.local/nuclei-templates")):
        if c and os.path.isdir(c):
            return c
    return ""


def _dossiers_nuclei(racine: str) -> list:
    """Sous-dossiers non intrusifs seulement (exposition, configuration, technologies) : evite de charger ~10 000 modeles (lent sur 8 Go)."""
    base = os.path.join(racine, "http")
    sel = [os.path.join(base, d) for d in ("exposures", "misconfiguration", "technologies", "exposed-panels", "miscellaneous", "cors") if os.path.isdir(os.path.join(base, d))]
    return sel or [racine]


def lancer_nmap(ctx, outil, ports: str = "top100", timeout=240) -> dict:
    ctx.garde.autoriser("outil_externe", ctx.cible.hote, None, "", "nmap", "reseau")
    cmd = [outil.chemin, "-sT", "-sV", "-Pn", "-T3", "--max-retries", "1", "-oX", "-"]
    cmd += ["--top-ports", "100"] if ports == "top100" else ["-p", ",".join(str(p) for p in ctx.cible.ports)]
    cmd.append(ctx.cible.hote)
    ex = executer(cmd, ctx.arret, timeout)
    res = {"outil": "nmap", "version": outil.version, "duree": round(ex.duree, 1), "code": ex.code, "expire": ex.expire, "arrete": ex.arrete}
    if ex.code != 0:
        ctx.limiter(f"nmap a échoué (code {ex.code}) : {(ex.erreur or ex.sortie)[:120]}")
        return res
    ouverts = [p for p in parser_nmap_xml(ex.sortie) if p[2] == "open"]
    ctx.faits["ports_ouverts"] = sorted(p[0] for p in ouverts)
    ctx.faits["scan_reseau"] = f"nmap {outil.version} (-sT -sV)"
    ctx.observer("nmap : " + (", ".join(f"{p[0]}/{p[1]} {p[3]} {p[4]}".strip() for p in ouverts) or "aucun port ouvert"))
    from modes.ghost_protocol.security.agent_reseau import RISQUES
    for port, proto, _, svc, ver in ouverts:
        if port in RISQUES and port not in ctx.cible.ports:
            nom, grav, impact = RISQUES[port]
            ctx.ajouter(Resultat(agent="OUTIL:nmap", categorie="service-expose", titre=f"Service {nom} accessible (port {port})", description=f"nmap : {port}/{proto} ouvert ({svc} {ver}).",
                                 gravite=grav, composant=f"{svc or nom} :{port}", ressource=f"{ctx.cible.hote}:{port}", methode=f"nmap {outil.version} -sT -sV",
                                 confiance=0.9, impact=impact, recommandation="Restreindre par pare-feu.", references=["CWE-668"], cle_validation="port_ouvert",
                                 donnees={"hote": ctx.cible.hote, "port": port}, preuves=[Preuve("nmap -sT -sV", None, f"{port}/{proto} open {svc} {ver}")]))
    res["ports_ouverts"] = len(ouverts)
    return res


def lancer_nuclei(ctx, outil, timeout=300) -> dict:
    ctx.garde.autoriser("outil_externe", ctx.cible.hote, ctx.cible.ports[0], "", "nuclei", "outils")
    modeles = _templates_nuclei()
    if not modeles:
        ctx.limiter("nuclei : aucun dossier de modèles (nuclei-templates) trouvé — exécutez « nuclei -update-templates » ou définissez JARVIS_SEC_NUCLEI_TEMPLATES.")
        return {"outil": "nuclei", "version": outil.version, "code": None, "note": "modèles absents"}
    cmd = [outil.chemin, "-u", ctx.cible.url_base(), "-jsonl", "-silent", "-duc", "-ni", "-nc", "-rl", "20", "-c", "10", "-timeout", "8", "-retries", "0",
           *[x for d in _dossiers_nuclei(modeles) for x in ("-t", d)], "-tags", "exposure,misconfig,tech,cors,disclosure,token,panel,config",
           "-etags", "dos,fuzz,intrusive,bruteforce,brute-force,default-login,rce,oast,xss,sqli,lfi,ssrf,takeover"]
    ex = executer(cmd, ctx.arret, timeout)
    res = {"outil": "nuclei", "version": outil.version, "duree": round(ex.duree, 1), "code": ex.code, "expire": ex.expire, "arrete": ex.arrete}
    trouves, hors = parser_nuclei(ex.sortie, ctx.cible.hote)
    for r in trouves:
        ctx.ajouter(r)
    if hors:
        ctx.journal.ecrire("HORS_PERIMETRE", outil="nuclei", ignores=hors)
        ctx.limiter(f"nuclei : {hors} résultat(s) hors périmètre ignorés.")
    if ex.code not in (0, None) and not trouves:
        ctx.limiter(f"nuclei a terminé avec le code {ex.code} : {(ex.erreur or '')[-160:]}")
    res["resultats"] = len(trouves)
    return res


def _chemin_code(ctx) -> str:
    return ctx.cible.chemin_code


def lancer_gitleaks(ctx, outil, timeout=300) -> dict:
    ctx.garde.autoriser("analyse_statique", "", None, "", "gitleaks", "code")
    racine = _chemin_code(ctx)
    with tempfile.TemporaryDirectory() as t:
        rapport = os.path.join(t, "gl.json")
        base = [outil.chemin, "dir", racine] if _ver(outil.version) >= (8, 19) else [outil.chemin, "detect", "--no-git", "--source", racine]
        ex = executer(base + ["--report-format", "json", "--report-path", rapport, "--exit-code", "0", "--no-banner", "--redact"], ctx.arret, timeout)
        contenu = Path(rapport).read_text(encoding="utf-8") if os.path.exists(rapport) else ""
    res = {"outil": "gitleaks", "version": outil.version, "duree": round(ex.duree, 1), "code": ex.code, "expire": ex.expire, "arrete": ex.arrete}
    if ex.code != 0:
        ctx.limiter(f"gitleaks a échoué (code {ex.code}) : {(ex.erreur or ex.sortie)[-150:]}")
        return res
    trouves = parser_gitleaks(contenu, racine)
    for r in trouves:
        ctx.ajouter(r)
    res["resultats"] = len(trouves)
    return res


def lancer_trivy(ctx, outil, timeout=600) -> dict:
    ctx.garde.autoriser("analyse_statique", "", None, "", "trivy", "code")
    ex = executer([outil.chemin, "fs", "--format", "json", "--quiet", "--no-progress", "--scanners", "vuln,secret", _chemin_code(ctx)], ctx.arret, timeout)
    res = {"outil": "trivy", "version": outil.version, "duree": round(ex.duree, 1), "code": ex.code, "expire": ex.expire, "arrete": ex.arrete}
    if ex.code != 0:
        ctx.limiter(f"trivy (vuln+secret) a échoué (code {ex.code}) : {(ex.erreur or '')[-200:]} — repli : secrets seulement, hors ligne.")
        ex = executer([outil.chemin, "fs", "--format", "json", "--quiet", "--no-progress", "--scanners", "secret", _chemin_code(ctx)], ctx.arret, timeout)
        res["repli_secrets"] = True
        if ex.code != 0:
            return res
    trouves = parser_trivy(ex.sortie)
    for r in trouves:
        ctx.ajouter(r)
    res["resultats"] = len(trouves)
    return res


def lancer_semgrep(ctx, outil, config: str = "auto", timeout=600) -> dict:
    ctx.garde.autoriser("analyse_statique", "", None, "", "semgrep", "code")
    ex = executer([outil.chemin, "scan", "--config", config, "--json", "--quiet", "--metrics", "off", "--timeout", "30", "--max-target-bytes", "1000000",
                   _chemin_code(ctx)], ctx.arret, timeout)
    res = {"outil": "semgrep", "version": outil.version, "duree": round(ex.duree, 1), "code": ex.code, "expire": ex.expire, "arrete": ex.arrete}
    if ex.code not in (0, 1):
        ctx.limiter(f"semgrep a échoué (code {ex.code}) : {(ex.erreur or '')[-160:]}")
        return res
    trouves = parser_semgrep(ex.sortie)
    for r in trouves:
        ctx.ajouter(r)
    res["resultats"] = len(trouves)
    return res


def lancer_zap(ctx, outil, timeout=900) -> dict:
    ctx.garde.autoriser("outil_externe", ctx.cible.hote, ctx.cible.ports[0], "", "zap-baseline", "outils")
    if not outil.chemin.endswith("zap-baseline.py"):
        ctx.limiter("ZAP détecté mais seul le mode « zap-baseline.py » (passif, sans attaque) est piloté ; le lancement graphique/actif n'est pas intégré.")
        return {"outil": "zap", "version": outil.version, "code": None, "note": "mode baseline absent"}
    with tempfile.TemporaryDirectory() as t:
        out = os.path.join(t, "zap.json")
        ex = executer([outil.chemin, "-t", ctx.cible.url_base(), "-J", out, "-I"], ctx.arret, timeout)
        contenu = Path(out).read_text(encoding="utf-8") if os.path.exists(out) else ""
    res = {"outil": "zap", "version": outil.version, "duree": round(ex.duree, 1), "code": ex.code, "expire": ex.expire, "arrete": ex.arrete}
    trouves = parser_zap(contenu, ctx.cible.hote)
    for r in trouves:
        ctx.ajouter(r)
    res["resultats"] = len(trouves)
    return res


def lancer_dependency_check(ctx, outil, timeout=1500) -> dict:
    ctx.garde.autoriser("analyse_statique", "", None, "", "dependency-check", "code")
    with tempfile.TemporaryDirectory() as t:
        ex = executer([outil.chemin, "--scan", _chemin_code(ctx), "--format", "JSON", "--out", t, "--disableAssembly"], ctx.arret, timeout)
        f = Path(t) / "dependency-check-report.json"
        contenu = f.read_text(encoding="utf-8") if f.exists() else ""
    res = {"outil": "dependency-check", "version": outil.version, "duree": round(ex.duree, 1), "code": ex.code, "expire": ex.expire, "arrete": ex.arrete}
    trouves = parser_depcheck(contenu)
    for r in trouves:
        ctx.ajouter(r)
    res["resultats"] = len(trouves)
    if ex.code not in (0, 1) and not trouves:
        ctx.limiter(f"dependency-check a échoué (code {ex.code}) : première exécution = téléchargement NVD très long ; {(ex.erreur or '')[-120:]}")
    return res


def _ver(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except ValueError:
        return (0,)


LANCEURS = {"nmap": lancer_nmap, "nuclei": lancer_nuclei, "gitleaks": lancer_gitleaks, "trivy": lancer_trivy, "semgrep": lancer_semgrep,
            "zap": lancer_zap, "dependency-check": lancer_dependency_check}
