"""Outil pour changer la personnalite de Jarvis a la voix."""
from core import config, personnalite
from core.registre import outil


@outil(
    nom="changer_personnalite",
    description="Change le mode de personnalite de l'assistant. A utiliser quand "
                "l'utilisateur dit 'passe en mode neutre', 'mode concis', 'mode "
                "jarvis', 'sois plus sarcastique', 'redeviens normal'.",
    parametres={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": "Mode voulu : jarvis_sarcastique, neutre, ou concis.",
            }
        },
        "required": ["mode"],
    },
)
def changer_personnalite(mode: str) -> str:
    """Change la personnalite et la persiste dans config.yaml."""
    nom = personnalite.normaliser(mode)
    if nom not in personnalite.PRESETS:
        return "Modes disponibles : jarvis, neutre, concis."
    config.definir("assistant.personnalite", nom)
    libelles = {"jarvis_sarcastique": "Jarvis", "neutre": "neutre", "concis": "concis"}
    return f"Mode {libelles.get(nom, nom)} active."
