"""Heure/date et minuteur."""
import threading
from datetime import datetime

from core import voix
from core.registre import outil


@outil(
    nom="heure_et_date",
    mcp_expose=True,
    description="Donne l'heure et la date actuelles",
)
def heure_et_date() -> str:
    """Donne l'heure et la date actuelles."""
    maintenant = datetime.now()
    jours = ["lundi", "mardi", "mercredi", "jeudi",
             "vendredi", "samedi", "dimanche"]
    mois = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
            "aout", "septembre", "octobre", "novembre", "decembre"]
    return (
        f"Il est {maintenant.hour} heures {maintenant.minute}, "
        f"le {jours[maintenant.weekday()]} {maintenant.day} "
        f"{mois[maintenant.month - 1]} {maintenant.year}."
    )


@outil(
    nom="lancer_minuteur",
    mcp_expose=True,
    description="Lance un minuteur qui previendra a voix haute",
    parametres={
        "type": "object",
        "properties": {
            "secondes": {"type": "integer", "description": "Duree en secondes"},
            "libelle": {"type": "string", "description": "Nom du minuteur"},
        },
        "required": ["secondes"],
    },
)
def lancer_minuteur(secondes: int, libelle: str = "") -> str:
    """Lance un minuteur qui previent a voix haute."""
    secondes = max(1, int(secondes))

    def sonner():
        texte = f"Le minuteur {libelle} est termine." if libelle \
            else "Le minuteur est termine."
        voix.parler(texte)

    threading.Timer(secondes, sonner).start()

    if secondes >= 60:
        duree = f"{secondes // 60} minutes"
    else:
        duree = f"{secondes} secondes"
    return f"Minuteur de {duree} lance."
