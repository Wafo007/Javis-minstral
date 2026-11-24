"""Commandes VOCALES de l'audit de securite (sans LLM, tolerantes aux accents). Actives UNIQUEMENT quand Ghost Protocol est actif.
L'enregistrement d'une cible (attestation) ne se fait JAMAIS a la voix : scripts/security_cible.py ou le HUD."""
from __future__ import annotations

import re

from modes.ghost_protocol.commandes import normaliser
from modes.ghost_protocol.state_manager import ETAT

_RX_URL = re.compile(r"(https?://[^\s,;\"']+)", re.I)
_RX_IP_DICTEE = re.compile(r"\b(\d{1,3}) point (\d{1,3}) point (\d{1,3}) point (\d{1,3})\b(?: (?:port|deux points) (\d{2,5}))?")
_RX_LOCALHOST = re.compile(r"\blocalhost(?: (?:port|deux points) (\d{2,5}))?")
_RX_PREPARE = re.compile(r"\bprepare\w*\b.*\baudit\b|\bnouvel audit\b")
_RX_LABO = re.compile(r"\b(?:analyse|audite|teste|scanne)\b.*\b(?:laboratoire|labo|juice shop|cette application)\b")
_RX_RECON = re.compile(r"\b(?:commence|lance|demarre)\w*\b.*\breconnaissance\b")
_RX_VULNS = re.compile(r"\banalyse\b.*\bvulnerabilites\b|\brecherche\b.*\bvulnerabilites\b")
_RX_VERIF = re.compile(r"\bverifie\w*\b.*\bresultats?\b|\bvalide\w*\b.*\b(?:resultats?|detections?)\b")
_RX_RAPPORT = re.compile(r"\bgenere\w*\b.*\brapport\b.*\bsecurite\b|\brapport de securite\b")
_RX_ARRET = re.compile(r"\b(?:arrete|stoppe|interromps|annule|coupe)\w*\b.*\b(?:audit|analyse de securite|scan)\b|\barret d urgence\b.*\b(?:audit|securite)\b|\bstop audit\b")
_RX_ETAT = re.compile(r"\b(?:etat|statut|point|avancement)\b.*\baudit\b|\bou en est l audit\b")
_RX_ACTIVITE_SECU = re.compile(r"\baudit\b|\bsecurite\b|\breconnaissance\b|\bvulnerabilites\b|\blaboratoire\b|\bjuice shop\b")
ALIAS = {"juice shop": "http://127.0.0.1:3000"}


def url_dictee(phrase: str) -> str:
    """URL ecrite ou dictee (« 127 point 0 point 0 point 1 port 3000 », « localhost port 8080 », « juice shop »)."""
    m = _RX_URL.search(phrase)
    if m:
        return m.group(1).rstrip(".,)")
    t = normaliser(phrase)
    m = _RX_IP_DICTEE.search(t)
    if m:
        return f"http://{'.'.join(m.group(i) for i in range(1, 5))}:{m.group(5) or 80}"
    m = _RX_LOCALHOST.search(t)
    if m:
        return f"http://localhost:{m.group(1) or 80}"
    for k, v in ALIAS.items():
        if k in t:
            return v
    return ""


def _svc():
    from modes.ghost_protocol.security import service
    return service()


def _resume(a) -> str:
    s = a.snapshot()
    return (f"Audit {s['etat'].lower()} sur {s['cible'] or 'aucune cible'} : {s['confirmes']} constats confirmés, "
            f"{s['potentiels']} à vérifier ou reproduits, {s['total']} au total.")


def essayer(phrase: str):
    """Reponse a dire, ou None si ce n'est pas une commande d'audit (ou si Ghost est inactif)."""
    if not (ETAT.actif and not ETAT.sortie_en_attente):
        return None
    t = normaliser(phrase)
    if not t or not _RX_ACTIVITE_SECU.search(t):
        return None
    if _RX_ARRET.search(t):
        a = _svc().audit
        if not a.en_cours and a.etat != "EN COURS":
            return "Aucun audit en cours, Commandant."
        return "Arrêt d'urgence exécuté. Toutes les tâches sont interrompues." if a.arreter("commande vocale") else "Arrêt demandé, les tâches se terminent."
    if _RX_ETAT.search(t):
        return _resume(_svc().audit)
    svc = _svc()
    a = svc.audit
    url = url_dictee(phrase)
    if _RX_VULNS.search(t):
        return _lancer(svc, "vulnerabilites", "Analyse des vulnérabilités lancée.")
    if _RX_LABO.search(t) or (_RX_PREPARE.search(t) and url):
        if not url:
            return "Quelle adresse dois-je analyser ? Elle doit être enregistrée comme laboratoire autorisé."
        ok, msg = a.preparer(url)
        if not ok:
            return f"Je ne peux pas analyser cette cible : {msg}"
        svc.url_courante = url
        a.lancer("complet", conseils_llm=True)
        return "Cible autorisée. Audit complet lancé, mode passif et limité. Dites « arrête l'audit » pour tout interrompre."
    if _RX_PREPARE.search(t):
        return ("Audit de sécurité prêt à préparer. Dites « analyse ce laboratoire » suivi de l'adresse. "
                "La cible doit d'abord être enregistrée avec son attestation, depuis le HUD ou le script de cibles.")
    if _RX_RECON.search(t):
        return _lancer(svc, "recon", "Reconnaissance autorisée lancée.")
    if _RX_VERIF.search(t):
        return _lancer(svc, "validation", "Vérification indépendante des résultats lancée.")
    if _RX_RAPPORT.search(t):
        return _lancer(svc, "rapport", "Génération du rapport de sécurité lancée.")
    return None


def _lancer(svc, mode: str, ok_msg: str) -> str:
    a = svc.audit
    if a.ctx is None:
        if svc.url_courante:
            ok, msg = a.preparer(svc.url_courante)
            if not ok:
                return f"Cible non utilisable : {msg}"
        else:
            return "Aucune cible préparée. Dites d'abord « analyse ce laboratoire » suivi de l'adresse."
    ok, msg = a.lancer(mode, conseils_llm=(mode == "recon"))
    return ok_msg if ok else f"Impossible : {msg}."
