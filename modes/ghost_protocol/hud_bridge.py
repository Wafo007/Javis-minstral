"""Pont vers le HUD (flux SSE existant de hud.py). Tout echec est silencieux : HUD ferme = Ghost continue.

Evenements emis (champ « t ») : ghost (etat global), ghost_term (ligne de terminal), ghost_mission (mission/progression/
menace/temps), ghost_voix (ELEVENLABS | FALLBACK | WINDOWS), ghost_rapport (bloc de rapport), ghost_script (script pret).
"""
from __future__ import annotations

import logging
import time

LOG = logging.getLogger("jarvis.ghost")
_DEBUT = [None]
JOURNAL: list = []          # derniers evenements emis (diagnostic et tests)


def _emettre(evenement: dict):
    JOURNAL.append(evenement)
    del JOURNAL[:-200]
    try:
        import hud
        hud.ghost(evenement)
    except Exception:
        pass                                           # HUD absent / ferme : sans consequence


def debut_session(maintenant=None):
    _DEBUT[0] = maintenant if maintenant is not None else time.time()


def horodatage() -> str:
    t = int(time.time() - (_DEBUT[0] or time.time()))
    return f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}"


def etat(snapshot: dict):
    _emettre({"t": "ghost", **snapshot})


def terminal(texte: str, niveau: str = "info"):
    _emettre({"t": "ghost_term", "h": horodatage(), "texte": str(texte), "niveau": niveau})


def mission(nom, etat_sim, progression, menace, temps_s, voix):
    _emettre({"t": "ghost_mission", "nom": nom, "etat": etat_sim, "progression": round(float(progression), 3),
              "menace": menace, "temps_s": int(temps_s), "voix": voix})


def voix(statut: str, genre: str = ""):
    _emettre({"t": "ghost_voix", "v": statut, "genre": genre})


def rapport(texte: str):
    _emettre({"t": "ghost_rapport", "texte": texte})


def script_pret(nom: str, lignes: int):
    _emettre({"t": "ghost_script", "nom": nom, "lignes": int(lignes)})
