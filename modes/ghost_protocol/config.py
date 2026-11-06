"""Configuration de GHOST PROTOCOL. Priorite : variable d'environnement > fichier .env > config.yaml.

Variables : ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL_ID. Aucune cle n'est jamais ecrite dans le code,
dans les journaux ni envoyee a un fournisseur LLM : ce module est la SEULE porte d'entree de la cle.
"""
from __future__ import annotations

import os
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
MODELE_DEFAUT = "eleven_flash_v2_5"
_CLES_ENV = ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID")


def _reglage(chemin, defaut=None):
    try:
        from core.config import reglage
        v = reglage(chemin, None)
    except Exception:
        v = None
    return defaut if v is None else v


def _fichier_env() -> dict:
    """Lit RACINE/.env (uniquement les variables ELEVENLABS_*). Ne modifie pas os.environ."""
    res = {}
    try:
        for ligne in (RACINE / ".env").read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            k, v = ligne.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            if k in _CLES_ENV:
                res[k] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return res


def _lire(nom_env, chemins_config):
    v = os.environ.get(nom_env, "").strip()
    if v:
        return v
    v = _fichier_env().get(nom_env, "").strip()
    if v:
        return v
    for c in chemins_config:
        v = str(_reglage(c, "") or "").strip()
        if v:
            return v
    return ""


def cle_api() -> str:
    return _lire("ELEVENLABS_API_KEY", ("ghost_protocol.elevenlabs.cle", "elevenlabs.cle"))


def voice_id() -> str:
    return _lire("ELEVENLABS_VOICE_ID", ("ghost_protocol.elevenlabs.voix",))


def model_id() -> str:
    return _lire("ELEVENLABS_MODEL_ID", ("ghost_protocol.elevenlabs.modele",)) or MODELE_DEFAUT


def langue() -> str:
    return str(_reglage("ghost_protocol.elevenlabs.langue", _reglage("elevenlabs.langue", "fr")) or "fr")


def reglages_voix() -> dict:
    """voice_settings envoyes a ElevenLabs : voix posee, assuree (stabilite haute, debit un peu plus lent)."""
    return {"stability": float(_reglage("ghost_protocol.voix.stabilite", 0.55)),
            "similarity_boost": float(_reglage("ghost_protocol.voix.similarite", 0.8)),
            "style": float(_reglage("ghost_protocol.voix.style", 0.35)),
            "speed": float(_reglage("ghost_protocol.voix.vitesse", 0.92)),
            "use_speaker_boost": True}


def max_caracteres() -> int:
    return max(40, int(_reglage("ghost_protocol.voix.max_caracteres", 220)))


def quota_mensuel() -> int:
    """Plafond LOCAL de caracteres par mois (0 = aucun). Ce n'est PAS le quota du compte ElevenLabs."""
    return max(0, int(_reglage("ghost_protocol.voix.quota_caracteres_mois", 0)))


def timeout_s() -> float:
    return max(2.0, float(_reglage("ghost_protocol.voix.timeout_s", 10)))


def cache_max_mo() -> int:
    return max(1, int(_reglage("ghost_protocol.voix.cache_mo", 50)))


def dossier_donnees() -> Path:
    d = RACINE / "logs" / "ghost"
    d.mkdir(parents=True, exist_ok=True)
    return d
