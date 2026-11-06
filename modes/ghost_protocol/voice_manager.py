"""Choix de la voix : Windows (comportement normal inchange) ou ElevenLabs Ghost -- jamais les deux a la fois.

Branche dans core/tts.tts() : tant que Ghost est inactif, ``provider_actif()`` renvoie None et le TTS existant
fonctionne EXACTEMENT comme avant (aucun appel ElevenLabs de ce module). Actif, il renvoie le provider Ghost, ou la voix
Windows si l'utilisatrice a coupe la voix Ghost. La lecture reste assuree par jarvis14.dire() (un seul lecteur,
verrou de parole) : pas de double lecture.
"""
from __future__ import annotations

import logging
import threading

from modes.ghost_protocol.state_manager import (ETAT, VOIX_ELEVENLABS, VOIX_FALLBACK, VOIX_INCONNUE, VOIX_WINDOWS)

LOG = logging.getLogger("jarvis.ghost")
_PROVIDER = [None]
_VERROU = threading.Lock()


def provider_ghost():
    with _VERROU:
        if _PROVIDER[0] is None:
            from modes.ghost_protocol.elevenlabs_provider import GhostElevenLabsProvider
            _PROVIDER[0] = GhostElevenLabsProvider()
        return _PROVIDER[0]


def remplacer_provider(provider):
    """Tests : injecte un provider factice (None = reinitialise)."""
    with _VERROU:
        _PROVIDER[0] = provider


def provider_actif():
    """Provider TTS a utiliser MAINTENANT, ou None (= comportement normal de core/tts)."""
    if not ETAT.actif:
        return None
    if ETAT.voix_coupee:
        from core.tts import WindowsProvider
        return WindowsProvider()
    return provider_ghost()


def couper_voix_ghost(coupee: bool = True):
    """Coupe/retablit la voix ElevenLabs Ghost (economie de quota) : Windows prend le relais."""
    ETAT.definir(voix_coupee=bool(coupee), voix=VOIX_WINDOWS if coupee else VOIX_INCONNUE)
    from modes.ghost_protocol import hud_bridge
    hud_bridge.voix(VOIX_WINDOWS if coupee else VOIX_INCONNUE)


def statut_texte() -> str:
    s = ETAT.voix
    if not ETAT.actif:
        return "Ghost Protocol est inactif : voix habituelle."
    return {VOIX_ELEVENLABS: "Voix Ghost ElevenLabs opérationnelle.",
            VOIX_FALLBACK: "Voix Ghost en repli sur la voix Windows : ElevenLabs sera retenté automatiquement.",
            VOIX_WINDOWS: "Voix Ghost coupée : j'utilise la voix Windows."}.get(s, "Voix Ghost prête, pas encore sollicitée.")
