"""GHOST PROTOCOL -- mode tactique cinematographique (SIMULATION uniquement) de Jarvis. Voir docs/GHOST_PROTOCOL.md."""
from __future__ import annotations

_CTRL = [None]


def controleur():
    """Controleur unique (cree a la demande)."""
    if _CTRL[0] is None:
        from modes.ghost_protocol.controller import GhostController
        _CTRL[0] = GhostController()
    return _CTRL[0]


def est_actif() -> bool:
    from modes.ghost_protocol.state_manager import ETAT
    return ETAT.actif
