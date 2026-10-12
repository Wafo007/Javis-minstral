"""Commandes comprises SANS LLM (instantanees, gratuites) : voix, modes, routines, proactivite.

essayer(phrase) -> texte a dire, ou None (la phrase continue vers le LLM comme avant).
"""
from __future__ import annotations

import re
import unicodedata

from core import accueil, modes_usage, routines, voix_profils


def _n(s):
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9' ]", " ", s).replace("'", " ").split())


_DESACTIVE = r"\b(desactive|desactiver|arrete|quitte|sors du|sortir du|enleve|coupe|retire)\b"
_ACTIVE = r"\b(active|activer|passe|passer|mets|mettre|met|bascule|lance|en mode|mode)\b"


def essayer(phrase, **rappels):
    p = _n(phrase)
    if not p:
        return None

    # --- voix ---------------------------------------------------------------
    if re.search(r"\b(quelles|quelle|liste|lister|donne|dis moi|montre)\b.*\bvoix\b", p) or \
            re.fullmatch(r"(les )?voix disponibles?", p):
        return voix_profils.liste_texte()
    if re.search(r"\bvoix\b.*\b(precedente|d avant|avant|ancienne)\b|\b(reviens|retourne|retour)\b.*\bvoix\b", p):
        return voix_profils.precedente()
    m = re.search(r"\b(?:utilise|mets|met|passe sur|passe a|prends|prend|change pour|choisis)\b\s+(?:la |une )?voix\s+(.+)", p)
    if m:
        return voix_profils.utiliser(m.group(1))

    # --- proactivite --------------------------------------------------------------
    if re.search(r"\bproactiv", p) or re.search(r"\b(parle|parler) (tout seul|sans qu on te|spontanement)\b", p):
        if re.search(_DESACTIVE + r"|\bnon\b|\bpas de\b|\bsans\b", p):
            return modes_usage.definir_proactif(False)
        return modes_usage.definir_proactif(True)

    # --- modes d'usage ----------------------------------------------------------------
    if re.search(r"\b(quel|dans quel) mode\b", p):
        return modes_usage.description()
    if re.search(r"\bmode\b|\bne pas deranger\b", p) or re.fullmatch(r"(retour|reviens)( au)? normal", p):
        mode = modes_usage.normaliser_mode(p)
        if mode and re.search(_DESACTIVE, p):
            return modes_usage.desactiver_mode(mode)
        if mode and (re.search(_ACTIVE, p) or "ne pas deranger" in p or len(p.split()) <= 3):
            return modes_usage.definir_mode(mode)
        if re.search(r"\b(retour|reviens)\b.*\bnormal\b", p):
            return modes_usage.definir_mode("normal")

    # --- routines ----------------------------------------------------------------------
    trouve = routines.trouver(phrase)
    if trouve:
        return routines.executer(trouve[0], trouve[1], nom_utilisateur=accueil.nom_utilisateur(), **rappels)
    return None
