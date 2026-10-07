"""Chargement de config.yaml : tous les secrets et reglages, au meme endroit.

Aucune cle en dur dans le code : tout passe par reglage("section.cle").
Le fichier config.yaml n'est pas versionne (voir .gitignore).
"""
from pathlib import Path

import yaml

_CONFIG = None
FICHIER = Path(__file__).resolve().parent.parent / "config.yaml"


def _charger():
    global _CONFIG
    if _CONFIG is None:
        try:
            _CONFIG = yaml.safe_load(FICHIER.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            _CONFIG = {}
    return _CONFIG


def reglage(chemin, defaut=None):
    """Lit une valeur imbriquee, ex. reglage("hue.pont").

    Renvoie `defaut` si le chemin n'existe pas ; renvoie la valeur telle quelle
    si elle vaut explicitement null (ex. audio.haut_parleur: null -> None).
    """
    valeur = _charger()
    for cle in chemin.split("."):
        if not isinstance(valeur, dict) or cle not in valeur:
            return defaut
        valeur = valeur[cle]
    return valeur


def definir(chemin, valeur):
    """Modifie une valeur (ex. 'assistant.personnalite') et reecrit config.yaml."""
    conf = _charger()
    noeud = conf
    cles = chemin.split(".")
    for cle in cles[:-1]:
        noeud = noeud.setdefault(cle, {})
    noeud[cles[-1]] = valeur
    with open(FICHIER, "w", encoding="utf-8") as f:
        yaml.safe_dump(conf, f, allow_unicode=True, sort_keys=False)
