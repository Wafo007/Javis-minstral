"""Messages d'erreur humains. Le detail technique reste dans les logs."""
from __future__ import annotations


def message_humain(exc, nom_outil=""):
    nom = (nom_outil or "").lower()
    if isinstance(exc, FileNotFoundError):
        return "Je n'ai pas trouvé ce fichier."
    if isinstance(exc, PermissionError):
        return "Je n'ai pas l'autorisation de faire ça."
    if isinstance(exc, TimeoutError) or type(exc).__name__ in ("Timeout", "ReadTimeout", "ConnectTimeout"):
        return "Le service met trop de temps à répondre. Je peux réessayer."
    if isinstance(exc, (ConnectionError, OSError)) and not isinstance(exc, (FileNotFoundError, PermissionError)):
        return "Le service est temporairement indisponible. Je peux réessayer."
    if any(m in nom for m in ("app", "ouvrir", "launch", "lancer")):
        return "Je n'ai pas réussi à ouvrir cette application."
    return "Je n'ai pas réussi à faire ça. Je peux réessayer."
