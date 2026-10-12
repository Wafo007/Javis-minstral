"""Salutation immediate apres « Hey Jarvis » : aucune requete LLM, aucune latence reseau.

Choisit une phrase courte selon l'heure, le mode et la derniere interaction.
Config (config.yaml) : section `accueil`, nom dans assistant.nom_utilisateur.
"""
from __future__ import annotations

import datetime as dt
import random
import time

try:
    from core.config import reglage as _reglage
except Exception:
    def _reglage(chemin, defaut=None):
        return defaut

NOM_DEFAUT = "Wafo Arold"
_ETAT = {"derniere": None, "dernier_choix": None}

PHRASES = {
    "normal": ["{salut} {nom}.", "{salut} {nom}, je vous écoute.", "{salut} {nom}, à votre service."],
    "retour": ["Ravi de vous revoir, {nom}.", "Ravi de vous revoir, {nom}. Je vous écoute."],
    "nuit": ["Oui, {nom}.", "{nom}, je vous écoute."],
    "court": ["Oui {nom}.", "Je vous écoute."],
}
_COURT = {"gaming", "travail", "ne_pas_deranger"}


def nom_utilisateur():
    nom = str(_reglage("assistant.nom_utilisateur", NOM_DEFAUT) or NOM_DEFAUT).strip()
    return nom.title() if nom.isupper() else nom     # « WAFO AROLD » -> « Wafo Arold » (le TTS ne l'epelle pas)


def salut_du_moment(now):
    return "Bonjour" if 5 <= now.hour < 18 else "Bonsoir"


def noter_interaction(instant=None):
    _ETAT["derniere"] = instant if instant is not None else time.time()


def salutation(now=None, mode="normal", instant=None, choix=None):
    """Texte de la salutation, ou None si desactivee."""
    if not bool(_reglage("accueil.actif", True)):
        return None
    now = now or dt.datetime.now()
    instant = instant if instant is not None else time.time()
    absence = float(_reglage("accueil.absence_minutes", 240) or 240) * 60
    derniere = _ETAT["derniere"]
    if mode == "nuit":
        cle = "nuit"
    elif mode in _COURT:
        cle = "court"
    elif derniere is not None and instant - derniere > absence:
        cle = "retour"
    else:
        cle = "normal"
    liste = _reglage(f"accueil.phrases.{cle}", None)
    liste = [p for p in liste if isinstance(p, str)] if isinstance(liste, list) and liste else PHRASES[cle]
    if bool(_reglage("accueil.variee", True)) and len(liste) > 1:
        autres = [p for p in liste if p != _ETAT["dernier_choix"]] or liste
        phrase = (choix or random.choice)(autres)
    else:
        phrase = liste[0]
    _ETAT["dernier_choix"] = phrase
    return phrase.format(salut=salut_du_moment(now), nom=nom_utilisateur())


def delai_apres():
    return float(_reglage("accueil.delai_apres", 0.4) or 0.0)
