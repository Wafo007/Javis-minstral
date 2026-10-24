"""Contexte recent des commandes (en memoire seulement, jamais ecrit sur disque).

Garde les 3 dernieres actions d'outils (nom + arguments courts) pendant 10 minutes et les
injecte dans la consigne du LLM : « Et apres-demain ? », « Non, Firefox », « Finalement 30 »
deviennent comprehensibles. Aucune conversation n'est stockee ici ; la memoire long terme
(memory.json) n'est pas touchee.
"""
from __future__ import annotations

import time

_ACTIONS = []          # [(instant, nom, args_courts)]
_DUREE = 600.0
_MAX = 3


def noter_action(nom, args=None, instant=None):
    courts = {}
    for k, v in (args or {}).items():
        if isinstance(v, (str, int, float, bool)):
            courts[k] = str(v)[:60]
    _ACTIONS.append((instant if instant is not None else time.time(), nom, courts))
    del _ACTIONS[:-_MAX]


def oublier():
    _ACTIONS.clear()


def recentes(instant=None):
    now = instant if instant is not None else time.time()
    return [(n, a) for t, n, a in _ACTIONS if now - t <= _DUREE]


def consigne(instant=None):
    """Complement de consigne : style de commande, actions multiples, corrections, contexte."""
    lignes = [
        "Commande simple reussie : reponds en 3 a 6 mots (ex. « Chrome est ouvert. »), sans formule "
        "de politesse. Details seulement pour une demande complexe.",
        "Si la demande contient plusieurs actions (« ouvre Chrome, lance YouTube et mets le volume a "
        "30 % »), appelle TOUS les outils necessaires, dans l'ordre, puis resume en une phrase.",
        "Si l'utilisateur corrige (« non, Firefox », « finalement 30 »), refais la derniere action avec "
        "la valeur corrigee, sans redemander ni confirmer. Une suite (« et apres-demain ? ») garde le "
        "sujet precedent.",
        "Pour ECRIRE du texte dans une application Windows (Bloc-notes, Word...) : ouvre-la avec l'outil "
        "d'ouverture d'application, puis appelle taper_texte avec le texte EXACT dicte (ponctuation et "
        "accents compris) et fenetre=<application>. L'outil noter sert UNIQUEMENT aux notes internes de "
        "Jarvis, jamais a saisir du texte dans une fenetre.",
        "N'annonce une action reussie que si l'outil l'a confirmee ; s'il signale un echec, un doute ou "
        "« non verifie », dis-le tel quel au lieu d'affirmer que c'est fait.",
    ]
    actions = recentes(instant)
    if actions:
        txt = "; ".join(f"{n}({', '.join(f'{k}={v}' for k, v in a.items())})" for n, a in actions)
        lignes.append(f"Actions recentes (de la plus ancienne a la plus recente) : {txt}.")
    return " ".join(lignes)
