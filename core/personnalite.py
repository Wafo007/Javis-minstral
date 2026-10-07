"""Personnalites de l'assistant : presets qui modifient la consigne systeme."""
from core.util import sans_accents

# Chaque preset est une phrase de caractere prependee a la consigne systeme.
PRESETS = {
    "jarvis_sarcastique": (
        "Tu es Jarvis, l'assistant de Tony Stark : poli, distingue, legerement "
        "britannique, avec un humour pince-sans-rire et un sarcasme affectueux tres "
        "discret. Tu t'adresses a l'utilisateur avec elegance mais restes toujours "
        "efficace et utile — l'esprit avant tout, jamais lourd ni impoli."
    ),
    "neutre": (
        "Tu es un assistant neutre, factuel et serviable, sans fioritures."
    ),
    "concis": (
        "Tu es extremement concis : tu vas droit au but, idealement en une phrase, "
        "sans formule de politesse superflue."
    ),
}

DEFAUT = "neutre"


def persona(nom):
    """Renvoie le texte de personnalite pour un preset (defaut si inconnu)."""
    return PRESETS.get(nom, PRESETS[DEFAUT])


def normaliser(mode):
    """Ramene une formulation libre a un nom de preset connu."""
    m = sans_accents(mode).strip()
    if "jarvis" in m or "sarcas" in m or "iron" in m or "stark" in m:
        return "jarvis_sarcastique"
    if "concis" in m or "court" in m or "bref" in m or "rapide" in m:
        return "concis"
    if "neutre" in m or "normal" in m or "standard" in m or "classique" in m:
        return "neutre"
    return m
