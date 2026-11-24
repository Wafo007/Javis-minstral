"""JARVIS AUTONOMOUS SECURITY INTELLIGENCE -- audit de securite AUTORISE (laboratoires/applications/code a soi) au-dessus de Ghost Protocol.
Voir docs/ARCHITECTURE_SECURITY_INTELLIGENCE.md et docs/GUIDE_JARVIS_SECURITY.md."""
from __future__ import annotations

import threading
from pathlib import Path

_SVC = [None]
_VERROU = threading.Lock()


def dossier_donnees() -> Path:
    try:
        from core.config import reglage
        d = reglage("ghost_protocol.security.dossier", None)
    except Exception:
        d = None
    from modes.ghost_protocol.config import RACINE
    return Path(d) if d else RACINE / "logs" / "security"


def _reglage(chemin, defaut):
    try:
        from core.config import reglage
        v = reglage(chemin, None)
    except Exception:
        v = None
    return defaut if v is None else v


class Service:
    """Registre + audit courant + etat de dialogue (cible courante)."""

    def __init__(self, dossier: Path | None = None, **kw):
        from modes.ghost_protocol.security.audit import Audit
        from modes.ghost_protocol.security.perimetre import Registre
        self.dossier = Path(dossier) if dossier else dossier_donnees()
        self.registre = Registre(self.dossier / "cibles.json")
        if "emettre" not in kw:
            from modes.ghost_protocol import hud_bridge
            kw["emettre"] = hud_bridge.securite
        if "conseiller" not in kw and _reglage("ghost_protocol.security.conseiller_llm", True):
            from modes.ghost_protocol.security.conseiller import ConseillerLLM
            kw["conseiller"] = ConseillerLLM()
        kw.setdefault("rps", float(_reglage("ghost_protocol.security.requetes_par_seconde", 8)))
        kw.setdefault("budget", int(_reglage("ghost_protocol.security.budget_requetes", 800)))
        self.audit = Audit(self.registre, self.dossier, **kw)
        self.url_courante = ""
        self.mode_code = False


def service() -> Service:
    with _VERROU:
        if _SVC[0] is None:
            _SVC[0] = Service()
        return _SVC[0]


def reinitialiser_pour_tests(svc=None):
    _SVC[0] = svc
