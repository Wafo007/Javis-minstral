"""Petites fonctions utilitaires partagees par le coeur et les outils."""
import re
import unicodedata


_DEBUTS_PARASITES = (
    re.compile(
        r"^(?:attends?|patiente(?: un peu)?|un instant|une seconde|deux secondes)"
        r"\s*[,.:;!…-]*\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:laisse(?:z)?[- ]moi\s+(?:regarder|v[ée]rifier|chercher|r[ée]fl[ée]chir)"
        r"(?:\s+(?:ça|cela))?)\s*[,.:;!…-]*\s*",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:je\s+(?:regarde|v[ée]rifie|cherche)(?:\s+(?:ça|cela|ta demande|pour toi))?)"
        r"\s*[.!…,:;-]+\s*",
        re.IGNORECASE,
    ),
)


def sans_accents(texte):
    """Minuscules, sans accents. Sert aux comparaisons souples."""
    t = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def nettoyer_reponse_vocale(texte):
    """Retire les amorces d'attente artificielles d'une réponse finale.

    Les vraies annonces de progression sont émises séparément, uniquement quand
    une recherche ou un outil lent est effectivement lancé. Une réponse finale
    ne doit donc jamais commencer par « Attends » ou « Un instant ».
    """
    propre = str(texte or "").strip()
    for _ in range(3):
        precedent = propre
        for motif in _DEBUTS_PARASITES:
            propre = motif.sub("", propre, count=1).strip()
        if propre == precedent:
            break
    if propre and propre[0].islower():
        propre = propre[0].upper() + propre[1:]
    return propre
