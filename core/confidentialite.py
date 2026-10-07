"""Filtre de confidentialite : caviarde les donnees sensibles d'un texte AVANT
de le prononcer a voix haute (garde-fou, ex. resume d'une delegation a Hermes).

Ce n'est pas un pare-feu parfait : c'est une derniere barriere qui masque les
motifs a risque evidents (mails, cles/jetons, numeros longs) et raccourcit le
texte pour une lecture vocale breve.
"""
import re

_MOTIFS = [
    # adresses e-mail
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[adresse mail]"),
    # cles/tokens a prefixe connu (sk-, pk-, ghp_, xoxb-, AKIA...)
    (re.compile(r"\b(?:sk|pk|ghp|gho|ghs|xox[baprs]|AKIA|AIza)[-_A-Za-z0-9]{10,}\b"),
     "[cle]"),
    # numeros longs (telephone, carte, IBAN grossier)
    (re.compile(r"\b(?:\+?\d[ .\-]?){9,}\d\b"), "[numero]"),
    # longues chaines opaques = jeton probable
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "[jeton]"),
]


def caviarder(texte: str) -> str:
    """Masque les motifs sensibles en conservant la mise en forme du texte."""
    t = str(texte or "")
    for motif, remplacement in _MOTIFS:
        t = motif.sub(remplacement, t)
    return t


def filtrer(texte: str, max_car: int = 500) -> str:
    """Caviarde mails/cles/numeros/jetons et raccourcit pour une lecture vocale."""
    t = caviarder(texte).strip()
    t = " ".join(t.split())              # normalise espaces / sauts de ligne
    if len(t) > max_car:
        t = t[:max_car].rsplit(" ", 1)[0].rstrip(",;:.") + "..."
    return t
