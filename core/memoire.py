"""Memoire long terme structuree, dans memory.json.

Structure : { "preferences": {}, "people": {}, "projects": {}, "facts": [] }
Fichier volontairement lisible et editable a la main.

Migre automatiquement l'ancien memoire.json (liste de faits) au premier chargement.
"""
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
FICHIER = RACINE / "memory.json"
ANCIEN = RACINE / "memoire.json"

_CLES = ("preferences", "people", "projects", "facts")


def _vide():
    return {"preferences": {}, "people": {}, "projects": {}, "facts": []}


def _normaliser(donnees):
    """Garantit les 4 cles avec le bon type."""
    m = _vide()
    if isinstance(donnees, dict):
        for cle in ("preferences", "people", "projects"):
            v = donnees.get(cle)
            if isinstance(v, dict):
                m[cle] = v
        faits = donnees.get("facts")
        if isinstance(faits, list):
            m["facts"] = faits
    return m


def _migrer_ancien():
    """Recupere les faits de l'ancien memoire.json, s'il existe."""
    if ANCIEN.exists():
        try:
            faits = json.loads(ANCIEN.read_text(encoding="utf-8")).get("faits", [])
            if faits:
                return {"facts": list(faits)}
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def charger():
    """Lit la memoire structuree. Migre l'ancien format au besoin."""
    if FICHIER.exists():
        try:
            return _normaliser(json.loads(FICHIER.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return _vide()
    memoire = _normaliser(_migrer_ancien())
    if any(memoire[c] for c in _CLES):
        sauver(memoire)     # persiste la migration
    return memoire


def sauver(memoire):
    FICHIER.write_text(
        json.dumps(_normaliser(memoire), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def texte_pour_systeme(memoire):
    """Resume la memoire pour l'injecter dans la consigne systeme."""
    parties = []
    if memoire.get("preferences"):
        parties.append("Preferences : " + " ; ".join(
            f"{k} = {v}" for k, v in memoire["preferences"].items()))
    if memoire.get("people"):
        parties.append("Personnes : " + " ; ".join(
            f"{k} = {v}" for k, v in memoire["people"].items()))
    if memoire.get("projects"):
        parties.append("Projets : " + " ; ".join(
            f"{k} = {v}" for k, v in memoire["projects"].items()))
    if memoire.get("facts"):
        parties.append("Faits : " + " ; ".join(memoire["facts"]))
    if not parties:
        return ""
    return ("\n\nCe que tu sais deja sur l'utilisateur "
            "(ne le recite pas spontanement, sers-t'en) :\n" + "\n".join(parties))
