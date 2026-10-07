"""Journalisation des appels d'outils et des erreurs vers logs/jarvis.log."""
import logging
from pathlib import Path

_LOG = None
DOSSIER = Path(__file__).resolve().parent.parent / "logs"


def obtenir():
    """Renvoie le logger 'jarvis' (le configure une seule fois)."""
    global _LOG
    if _LOG is None:
        DOSSIER.mkdir(exist_ok=True)
        handler = logging.FileHandler(DOSSIER / "jarvis.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
        _LOG = logging.getLogger("jarvis")
        _LOG.setLevel(logging.INFO)
        _LOG.handlers.clear()
        _LOG.addHandler(handler)
        _LOG.propagate = False
    return _LOG
