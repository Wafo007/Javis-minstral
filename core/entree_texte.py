"""Entree TEXTE de Jarvis : ecrire une demande au clavier au lieu de la dire.

Principe : deux entrees, une seule sortie.
  - entrees : la voix (micro + Whisper) OU le clavier (champ de saisie du HUD, console) ;
  - sortie  : TOUJOURS vocale (le texte tape suit exactement le meme pipeline que la voix
    transcrite : commandes locales, routage, LLM, outils, permissions N1/N2/N3, puis ``dire``).

Ce module ne fait QUE transporter et valider le texte : il ne connait ni le LLM ni les outils.
Il est thread-safe (le HUD HTTP et la console l'alimentent, la boucle principale le consomme)
et n'importe aucune dependance lourde, donc testable sans micro ni reseau.

Securite :
  - le texte est borne (longueur) et nettoye (caracteres de controle) ;
  - la file est bornee et un delai minimum separe deux envois (pas de saturation) ;
  - une action sensible declenchee par ecrit passe par les memes confirmations que la voix ;
    la confirmation ECRITE n'est acceptee pour un N3 que si ``texte.confirmation_ecrite_n3``
    est vrai (defaut : faux -> un N3 se confirme a la voix).
"""
from __future__ import annotations

import logging
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass

from core.config import reglage

LOG = logging.getLogger("jarvis.texte")

LONGUEUR_MAX_DEFAUT = 1000
TAILLE_FILE_MAX = 5
DELAI_MIN_ENVOIS = 0.25     # secondes entre deux envois acceptes

_ORIGINES = frozenset({"hud", "console", "test"})
_CONTROLES = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANCS = re.compile(r"\s+")


@dataclass(frozen=True)
class EntreeTexte:
    """Une demande ecrite : le texte nettoye et son origine."""
    texte: str
    origine: str


class RefusEntree(ValueError):
    """Entree refusee (vide, trop longue, file pleine, trop rapide, desactive)."""


_FILE: "queue.Queue[EntreeTexte]" = queue.Queue(maxsize=TAILLE_FILE_MAX)
_VERROU = threading.Lock()
_dernier_envoi = 0.0
_console: threading.Thread | None = None


def actif() -> bool:
    """Vrai si l'entree clavier est activee (config ``texte.actif``, vrai par defaut)."""
    return bool(reglage("texte.actif", True))


def longueur_max() -> int:
    try:
        valeur = int(reglage("texte.longueur_max", LONGUEUR_MAX_DEFAUT) or LONGUEUR_MAX_DEFAUT)
    except (TypeError, ValueError):
        valeur = LONGUEUR_MAX_DEFAUT
    return max(20, min(valeur, 4000))


def nettoyer(texte) -> str:
    """Texte propre : sans caracteres de controle, espaces normalises (retours a la ligne -> espace)."""
    brut = _CONTROLES.sub("", str(texte or ""))
    return _BLANCS.sub(" ", brut).strip()


def soumettre(texte, origine: str = "hud") -> str:
    """Met une demande ecrite en file. Renvoie le texte nettoye retenu.

    Leve ``RefusEntree`` (message affichable) si l'entree est desactivee, vide, trop longue,
    trop rapprochee de la precedente ou si la file est pleine.
    """
    if not actif():
        raise RefusEntree("La saisie au clavier est desactivee (texte.actif).")
    if origine not in _ORIGINES:
        origine = "hud"
    propre = nettoyer(texte)
    if not propre:
        raise RefusEntree("Message vide.")
    if len(propre) > longueur_max():
        raise RefusEntree(f"Message trop long (maximum {longueur_max()} caracteres).")
    global _dernier_envoi
    with _VERROU:
        maintenant = time.monotonic()
        if maintenant - _dernier_envoi < DELAI_MIN_ENVOIS:
            raise RefusEntree("Doucement : un message a la fois.")
        try:
            _FILE.put_nowait(EntreeTexte(propre, origine))
        except queue.Full:
            raise RefusEntree("Jarvis a deja des messages en attente : patiente un instant.") from None
        _dernier_envoi = maintenant
    LOG.info("entree texte (%s) : %d caracteres", origine, len(propre))
    return propre


def prendre(timeout: float | None = 0.0) -> EntreeTexte | None:
    """Retire la prochaine demande ecrite, ou None. ``timeout`` 0 = sans attendre."""
    try:
        if timeout is None or timeout > 0:
            return _FILE.get(timeout=timeout)
        return _FILE.get_nowait()
    except queue.Empty:
        return None


def en_attente() -> bool:
    """Vrai si au moins une demande ecrite attend d'etre traitee."""
    return not _FILE.empty()


def vider() -> int:
    """Jette les demandes en attente (arret, changement de contexte). Renvoie le nombre jete."""
    n = 0
    while prendre(0.0) is not None:
        n += 1
    return n


def confirmation_ecrite_permise(niveau_outil: str) -> bool:
    """Peut-on confirmer PAR ECRIT une action de ce niveau (N1/N2/N3) ?

    N2 : oui (reglage ``texte.confirmation_ecrite``, vrai par defaut). N3 : seulement si
    l'utilisateur l'a explicitement choisi (``texte.confirmation_ecrite_n3``), sinon vocal.
    """
    if not actif() or not bool(reglage("texte.confirmation_ecrite", True)):
        return False
    if niveau_outil == "N3":
        return bool(reglage("texte.confirmation_ecrite_n3", False))
    return True


def delai_confirmation() -> float:
    """Secondes laissees pour taper une confirmation avant annulation (5 a 120)."""
    try:
        valeur = float(reglage("texte.delai_confirmation", 20) or 20)
    except (TypeError, ValueError):
        valeur = 20.0
    return max(5.0, min(valeur, 120.0))


# ---------------------------------------------------------------- console (stdin)

def _boucle_console():
    """Lit les lignes tapees dans le terminal de Jarvis et les met en file."""
    while True:
        try:
            ligne = sys.stdin.readline()
        except (OSError, ValueError):
            return
        if ligne == "":          # EOF : le terminal est ferme
            return
        if not ligne.strip():
            continue
        try:
            soumettre(ligne, origine="console")
        except RefusEntree as exc:
            print(f"  [texte] {exc}")


def demarrer_console() -> bool:
    """Active la saisie dans le terminal (thread daemon). Sans effet si stdin n'est pas interactif.

    Renvoie True si la saisie console est active.
    """
    global _console
    if not actif() or not bool(reglage("texte.console", True)):
        return False
    if _console is not None and _console.is_alive():
        return True
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError, OSError):
        return False
    _console = threading.Thread(target=_boucle_console, daemon=True, name="entree-texte-console")
    _console.start()
    return True
