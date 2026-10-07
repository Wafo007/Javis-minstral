"""Pont vers la synthese vocale.

Permet aux outils (ex. le minuteur) de parler sans dependre de jarvis14.py,
ce qui evite les imports circulaires. jarvis14 enregistre sa fonction `dire`
via definir_parleur() au demarrage.
"""
_parleur = None


def definir_parleur(fonction):
    global _parleur
    _parleur = fonction


def parler(texte):
    if _parleur is not None:
        _parleur(texte)
