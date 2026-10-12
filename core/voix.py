"""Pont vers la synthese vocale.

Permet aux outils (ex. le minuteur) de parler sans dependre de jarvis14.py,
ce qui evite les imports circulaires. jarvis14 enregistre sa fonction `dire`
via definir_parleur() au demarrage.
"""
_parleur = None


def definir_parleur(fonction):
    global _parleur
    _parleur = fonction


def parler(texte, importance="critique"):
    try:
        from core import modes_usage
        if not modes_usage.proactif_autorise(importance):
            return                     # mode nuit / ne pas deranger : annonce spontanee supprimee
    except Exception:
        pass
    if _parleur is not None:
        _parleur(texte)
