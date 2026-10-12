"""Routines : une phrase declenche plusieurs actions (modes, outils, phrase finale).

Config (config.yaml) :
  routines:
    commencer_journee:
      phrases: ["commence ma journee", "demarre ma journee"]
      mode: travail                       # optionnel : mode d'usage a activer
      actions:                            # outils existants du registre, dans l'ordre
        - {outil: ouvrir_application, args: {nom: "Chrome"}}
        - {outil: regler_volume, args: {niveau: 30}}
      dire: "C'est parti, {nom}."         # optionnel
Un outil qui demande confirmation n'est JAMAIS execute par une routine (securite).
"""
from __future__ import annotations

import logging
import re
import unicodedata

try:
    from core.config import reglage as _reglage
except Exception:
    def _reglage(chemin, defaut=None):
        return defaut

LOG = logging.getLogger("jarvis.routines")


def _n(s):
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def trouver(phrase):
    """(nom, definition) de la routine dont une phrase est contenue dans la demande."""
    conf = _reglage("routines", None)
    p = _n(phrase)
    if not isinstance(conf, dict) or not p:
        return None
    for nom, d in conf.items():
        if not isinstance(d, dict):
            continue
        for ph in d.get("phrases") or []:
            if _n(ph) and _n(ph) in p:
                return nom, d
    return None


def executer(nom, d, registre=None, modes=None, nom_utilisateur="", dire_cb=None):
    """Execute une routine ; renvoie la phrase a dire."""
    if registre is None:
        from core import registre as _registre
        registre = _registre
    if modes is None:
        from core import modes_usage as modes
    ratees, ok = [], 0
    if d.get("mode"):
        modes.definir_mode(str(d["mode"]))
    for action in d.get("actions") or []:
        outil_nom = (action or {}).get("outil", "")
        outil = registre.get(outil_nom)
        if outil is None:
            LOG.warning("routine %s : outil inconnu %s", nom, outil_nom)
            ratees.append(outil_nom)
            continue
        if getattr(outil, "confirmation", False):
            LOG.warning("routine %s : %s demande confirmation, ignore", nom, outil_nom)
            ratees.append(outil_nom)
            continue
        try:
            registre.executer(outil, dict(action.get("args") or {}))
            ok += 1
        except Exception:
            LOG.exception("routine %s : %s a echoue", nom, outil_nom)
            ratees.append(outil_nom)
    texte = str(d.get("dire") or "Routine terminée.").replace("{nom}", nom_utilisateur)
    if ratees:
        texte += f" {len(ratees)} action{'s' if len(ratees) > 1 else ''} n'{'ont' if len(ratees) > 1 else 'a'} pas abouti."
    return texte
