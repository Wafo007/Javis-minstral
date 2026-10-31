"""Missions autonomes d'auto-amelioration par la voix (moteur : core/missions.py + core/mission_agent.py).

« Jarvis, ameliore ton systeme de routage. Tu disposes de 60 minutes. » -> une mission tourne dans un processus
separe, dans un workspace git isole ; la version stable n'est jamais modifiee. Ce module ne contient que le
routage de la voix (deterministe, avant le LLM) et les outils minces qui appellent le moteur.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from core import missions as M
from core.registre import outil
from core.resultat import ResultatOutil
from core.util import sans_accents

LOG = logging.getLogger("jarvis.tools.missions")

_NOMBRES = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "dix": 10, "quinze": 15, "vingt": 20,
            "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}
_VERBES = ("ameliore", "ameliorer", "analyse", "analyser", "corrige", "corriger", "optimise", "optimiser",
           "renforce", "refactorise", "auto ameliore", "auto ameliorer", "ameliorons")
_CIBLE = re.compile(r"\b(ton|ta|tes|le|la|les|ses|son) (code|systeme|routage|routeur|module|memoire|architecture|moteur|"
                    r"pipeline|gestion|probleme|problemes|bug|bugs|source|sources|performances?)\b|\brout")
_CUE_LONG = re.compile(r"\b(mission|campagne|tu disposes|disposes de|autonome|sans mon intervention|pendant|durant|"
                       r"auto ameliorat|auto amelioration|en mon absence)\b")


def _norm(phrase) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sans_accents(str(phrase or "").lower())).split())


def extraire_duree_minutes(phrase):
    """Duree annoncee dans la phrase (« 60 minutes », « deux heures », « 1h30 », « une demi heure »), sinon None."""
    n = _norm(phrase)
    if re.search(r"\bdemi heure\b", n) and not re.search(r"\b(une|1|deux|2|trois|3)\s+heures?\s+et\s+demie", n):
        return 30.0
    m = re.search(r"\b(\d+|" + "|".join(_NOMBRES) + r") ?h ?(\d{1,2})?\b|\b(\d+|" + "|".join(_NOMBRES)
                  + r") heures? (?:et )?(demie|(\d{1,2}))?", n)
    total = None
    mh = re.search(r"\b(\d+|" + "|".join(_NOMBRES) + r") (?:heures?|h)\b(?: et (demie)| (\d{1,2})\b)?", n)
    if mh:
        h = float(mh.group(1)) if mh.group(1).isdigit() else float(_NOMBRES[mh.group(1)])
        total = h * 60 + (30 if mh.group(2) else (float(mh.group(3)) if mh.group(3) else 0))
    mm = re.search(r"\b(\d+|" + "|".join(_NOMBRES) + r") (?:minutes?|mins?)\b", n)
    if mm and total is None:
        total = float(mm.group(1)) if mm.group(1).isdigit() else float(_NOMBRES[mm.group(1)])
    mc = re.search(r"\b(\d{1,2}) ?h ?(\d{2})\b", sans_accents(str(phrase).lower()))
    if mc:
        total = int(mc.group(1)) * 60 + int(mc.group(2))
    del m
    return total


def _existe_mission() -> bool:
    try:
        return bool(M.MissionStore().lister(False, 1))
    except Exception:
        return False


def router_mission(phrase, piece=""):
    """Route deterministe des commandes de mission ; None si la phrase n'en est pas une (rien n'est capte a tort)."""
    n = _norm(phrase)
    if not n:
        return None
    if re.search(r"\bmission\b", n) or "rapport" in n:
        if re.search(r"\b(arret d urgence|stoppe immediatement|stop immediat|arrete immediatement|urgence)\b", n) \
                and "mission" in n:
            return "mission_urgence", {}
        if re.search(r"\b(annule|annuler|abandonne|arrete|stoppe)\b.*\bmission\b", n):
            return "mission_annuler", {}
        if re.search(r"\b(pause|suspends|suspend)\b", n) and "mission" in n:
            return "mission_pause", {}
        if re.search(r"\b(reprends|reprend|reprendre|relance|continue)\b.*\bmission\b", n):
            return "mission_reprendre", {}
        if re.search(r"\b(ou en est|etat|avancement|progression|statut|ca avance|point sur)\b", n) and "mission" in n:
            return "mission_statut", {}
        if re.search(r"\b(applique|integre|integrer|fusionne|deploie)\b.*\b(modifications?|mission|changements?)\b", n):
            return "mission_integrer", {}
        if re.search(r"\b(liste|lister|quelles?|historique)\b.*\bmissions?\b", n):
            return "mission_lister", {}
    if re.search(r"\b(montre|affiche|lis|donne|ouvre)\b.*\brapport( complet| final| de mission)?$", n) \
            and (_existe_mission() or "mission" in n):
        return "mission_rapport", {}
    # Lancement : un verbe d'amelioration + une cible « Jarvis » (code, routage...) + un indice de mission longue,
    # ou « analyse ton code / ton systeme de ... ». Les commandes Windows (ouvre, clique, tape...) n'ont aucun de ces mots.
    if any(re.search(rf"\b{re.escape(v)}\b", n) for v in _VERBES) and _CIBLE.search(n):
        duree = extraire_duree_minutes(phrase)
        if _CUE_LONG.search(n) or duree or re.search(r"\b(analyse|analyser)\b.*\b(ton|ta|tes)\b", n):
            return "mission_demarrer", {"objectif": str(phrase).strip(), **({"duree_minutes": duree} if duree else {})}
    if re.search(r"\bcampagne\b", n) and re.search(r"\bameliorat|\bauto", n):
        return "mission_demarrer", {"objectif": str(phrase).strip()}
    return None


def _store():
    return M.MissionStore()


def _ok(msg, **det):
    return ResultatOutil(msg, succes=True, verifie=True, details=det)


def _ko(msg, erreur="mission"):
    return ResultatOutil(msg, succes=False, erreur=erreur)


@outil(
    nom="mission_demarrer",
    description="Lance une MISSION AUTONOME d'auto-amelioration du code de Jarvis (processus separe, workspace git isole, "
                "tests, rapport). Pour « ameliore ton systeme de routage, tu disposes de 60 minutes », « analyse ton systeme "
                "de memoire », « lance une campagne d'auto-amelioration ». Duree par defaut 60 min, maximum 120.",
    parametres={"type": "object", "properties": {"objectif": {"type": "string"},
                                                   "duree_minutes": {"type": "number"}}, "required": ["objectif"]},
)
def mission_demarrer(objectif: str, duree_minutes: float | None = None):
    try:
        m = M.demarrer_mission(objectif, duree_minutes, store=_store())
    except M.ErreurMission as exc:
        return _ko(str(exc), "refus")
    return _ok(f"C'est parti : mission {m['numero']} lancée, {int(m['duree_max_s'] // 60)} minutes au maximum, "
               "dans un espace de travail isolé. Ta version stable n'est pas touchée. Je te préviens à la fin.",
               mission=m["id"], branche=m["branche"])


@outil(nom="mission_statut", description="Etat d'avancement de la mission d'auto-amelioration en cours ou la derniere : "
                                          "« ou en est ta mission ? ».", parametres={"type": "object", "properties": {}})
def mission_statut():
    s = _store()
    try:
        m = M._cible(s, None, actives=False)
    except M.ErreurMission as exc:
        return _ko(str(exc))
    return _ok(M.resume_statut(m, s), mission=m["id"], statut=m["statut"])


@outil(nom="mission_pause", description="Met la mission en pause (apres l'etape en cours) : « mets ta mission en pause ».",
       parametres={"type": "object", "properties": {}})
def mission_pause():
    try:
        m = M.mettre_en_pause(_store())
    except M.ErreurMission as exc:
        return _ko(str(exc))
    return _ok(f"Pause demandée pour la mission {m['numero']} : elle s'arrête après l'étape en cours.")


@outil(nom="mission_reprendre", description="Reprend la mission en pause ou interrompue : « reprends ta mission ».",
       parametres={"type": "object", "properties": {}})
def mission_reprendre():
    try:
        m = M.reprendre(_store())
    except M.ErreurMission as exc:
        return _ko(str(exc))
    return _ok(f"Je reprends la mission {m['numero']}.")


@outil(nom="mission_annuler", description="Annule la mission en cours (arret propre, workspace et journaux conserves) : "
                                           "« annule la mission ».", parametres={"type": "object", "properties": {}})
def mission_annuler():
    try:
        m = M.annuler(_store())
    except M.ErreurMission as exc:
        return _ko(str(exc))
    return _ok(f"Annulation demandée pour la mission {m['numero']} : arrêt propre en cours, rien n'est supprimé.")


@outil(nom="mission_urgence", description="Arret D'URGENCE de la mission (tue immediatement ses processus) : « arret d'urgence "
                                           "de la mission ».", parametres={"type": "object", "properties": {}})
def mission_urgence():
    try:
        m = M.annuler(_store(), urgence=True)
    except M.ErreurMission as exc:
        return _ko(str(exc))
    return _ok(f"Arrêt d'urgence effectué : mission {m['numero']} stoppée ({m['statut'].lower()}).")


@outil(nom="mission_lister", description="Liste les missions d'auto-amelioration recentes.",
       parametres={"type": "object", "properties": {}})
def mission_lister():
    liste = _store().lister(False, 8)
    if not liste:
        return _ok("Aucune mission enregistrée.")
    return _ok("; ".join(f"mission {m['numero']} : {m['statut'].lower()} ({m['objectif'][:40]})" for m in liste))


@outil(nom="mission_rapport", description="Donne le rapport de la derniere mission (resume + emplacement du rapport complet) : "
                                           "« montre-moi ton rapport ».", parametres={"type": "object", "properties": {}})
def mission_rapport():
    s = _store()
    try:
        m = M._cible(s, None, actives=False)
    except M.ErreurMission as exc:
        return _ko(str(exc))
    rapport = Path(m["rapports"]) / "report.md"
    if not rapport.exists():
        return _ko(f"Le rapport de la mission {m['numero']} n'est pas encore prêt : {M.resume_statut(m, s)}", "absent")
    return _ok(f"{M.resume_statut(m, s)} Le rapport complet est dans {rapport}.", chemin=str(rapport))


def _annonce_integration(args):
    return ("Je vais appliquer à ta version stable les modifications vérifiées de la dernière mission (sans commit). "
            "Tu confirmes ?")


@outil(nom="mission_integrer", confirmation=True, annonce=_annonce_integration,
       description="Applique au projet STABLE le candidat verifie de la derniere mission (git apply, sans commit). "
                   "Action critique : confirmation vocale a chaque fois.",
       parametres={"type": "object", "properties": {}})
def mission_integrer():
    try:
        res = M.integrer_mission(_store(), autorise=True)      # n'est atteint qu'apres la confirmation N3
    except M.ErreurMission as exc:
        return _ko(str(exc), "refus")
    return _ok(f"Intégré : {len(res['fichiers'])} fichier(s) appliqués à la version stable. Relis le diff puis commite.",
               fichiers=res["fichiers"])
