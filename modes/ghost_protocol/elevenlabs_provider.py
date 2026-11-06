"""Voix GHOST : ElevenLabs avec cache, plafond de caracteres, disjoncteur et repli Windows automatique.

S'insere dans l'abstraction existante (core/tts.py) : ``synthetiser(texte)`` renvoie ``(int16, 24000)`` ou ``None`` ;
sur ``None``, jarvis14.dire() parle avec la voix Windows (SAPI) -- c'est le repli. Jamais d'exception vers l'appelant,
jamais d'attente illimitee (timeout court), jamais de cle dans les journaux.

Ce qui est reellement facture : seuls les appels HTTP aboutis. Les phrases en cache, trop courtes ou purement techniques
ne partent pas. Le quota du compte ElevenLabs depend de l'offre en vigueur : ce module n'affirme aucune duree gratuite ;
il compte les caracteres ENVOYES et peut appliquer un plafond mensuel local (``ghost_protocol.voix.quota_caracteres_mois``).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request

from modes.ghost_protocol import config as cfg
from modes.ghost_protocol.audio_cache import CacheAudio
from modes.ghost_protocol.state_manager import (ETAT, VOIX_ELEVENLABS, VOIX_FALLBACK)

LOG = logging.getLogger("jarvis.ghost")
URL_TTS = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"

# Duree pendant laquelle on n'appelle plus ElevenLabs apres une erreur (puis reessai automatique).
DELAIS = {"cle_invalide": 3600, "quota": 1800, "reseau": 45, "timeout": 45, "generation": 120}
DELAI_MAX_RESEAU = 600


class ErreurVoix(Exception):
    def __init__(self, genre, detail=""):
        super().__init__(f"{genre} {detail}".strip())
        self.genre, self.detail = genre, detail


def classer_http(statut: int, corps: bytes = b"") -> str:
    """Genre d'erreur selon le code HTTP (401/403 : cle ; 429 ou « quota » : quota ; 422 : requete refusee)."""
    texte = (corps or b"")[:600].decode("utf-8", "replace").lower()
    if statut in (401, 403):
        return "quota" if "quota" in texte and statut == 403 else "cle_invalide"
    if statut == 429 or "quota_exceeded" in texte or "quota" in texte:
        return "quota"
    if statut >= 500 or statut in (408, 425):
        return "reseau"
    return "generation"


def http_urllib(url, corps: bytes, entetes: dict, timeout: float):
    """(statut, octets). Les erreurs HTTP sont renvoyees comme un statut ; reseau/timeout levent ErreurVoix."""
    req = urllib.request.Request(url, data=corps, method="POST", headers=entetes)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        except Exception:
            return e.code, b""
    except TimeoutError as e:
        raise ErreurVoix("timeout", str(e)) from None
    except urllib.error.URLError as e:
        if "timed out" in str(e.reason).lower():
            raise ErreurVoix("timeout", str(e.reason)) from None
        raise ErreurVoix("reseau", str(e.reason)) from None
    except OSError as e:
        raise ErreurVoix("reseau", str(e)) from None


def preparer_texte(texte: str, maxi: int):
    """Texte a synthetiser, ou None si inutile (vide, symboles seuls, message purement technique)."""
    t = " ".join(str(texte or "").split())
    if len(t) < 2 or not re.search(r"[A-Za-zÀ-ÿ]{2,}", t):
        return None
    if re.fullmatch(r"[\[\(]?(ok|oui|non|ack|ping|pong|done|erreur \d+)[\]\)]?[.!]?", t, re.I):
        return None
    if len(t) > maxi:
        coupe = t[:maxi]
        fin = max(coupe.rfind(". "), coupe.rfind("! "), coupe.rfind("? "), coupe.rfind("; "))
        t = coupe[:fin + 1] if fin >= maxi * 0.4 else coupe.rsplit(" ", 1)[0]
    return t.strip()


class UsageVoix:
    """Compteur persistant de caracteres envoyes (mois courant) -- information locale, pas le solde du compte."""

    def __init__(self, fichier=None, maintenant=dt.date.today):
        self.fichier = fichier
        self._maintenant = maintenant
        self.donnees = {"mois": "", "caracteres": 0, "appels": 0, "cache": 0}
        self._charger()

    def _mois(self):
        return self._maintenant().strftime("%Y-%m")

    def _charger(self):
        try:
            if self.fichier:
                self.donnees.update(json.loads(open(self.fichier, encoding="utf-8").read()))
        except (OSError, ValueError):
            pass
        if self.donnees.get("mois") != self._mois():
            self.donnees = {"mois": self._mois(), "caracteres": 0, "appels": 0, "cache": 0}

    def ajouter(self, caracteres=0, cache=False):
        if self.donnees.get("mois") != self._mois():
            self.donnees = {"mois": self._mois(), "caracteres": 0, "appels": 0, "cache": 0}
        if cache:
            self.donnees["cache"] += 1
        else:
            self.donnees["caracteres"] += int(caracteres)
            self.donnees["appels"] += 1
        try:
            if self.fichier:
                with open(self.fichier, "w", encoding="utf-8") as f:
                    json.dump(self.donnees, f)
        except OSError:
            pass

    @property
    def caracteres(self):
        return self.donnees["caracteres"]


def _decoder(donnees: bytes, mp3: bool):
    import numpy as np
    if mp3:
        import miniaudio
        pcm = miniaudio.decode(donnees, nchannels=1, sample_rate=24000,
                               output_format=miniaudio.SampleFormat.SIGNED16).samples
        return np.frombuffer(bytes(pcm) if not isinstance(pcm, (bytes, bytearray)) else pcm, dtype=np.int16)
    donnees = donnees[:len(donnees) - len(donnees) % 2]
    return np.frombuffer(donnees, dtype=np.int16)


class GhostElevenLabsProvider:
    """Provider TTS compatible core.tts.ProviderTTS (nom, disponible, synthetiser)."""

    nom = "GhostElevenLabs"

    def __init__(self, http=http_urllib, cache=None, usage=None, horloge=time.time, decodeur=None, budget=True):
        self._http = http
        self._horloge = horloge
        self.cache = cache or CacheAudio(cfg.dossier_donnees() / "cache_audio", cfg.cache_max_mo() * 1024 * 1024)
        self.usage = usage or UsageVoix(cfg.dossier_donnees() / "usage.json")
        self._decodeur = decodeur                       # injectable (tests) : decodeur(bytes) -> ndarray int16
        self._budget = budget
        self._bloque_jusqua = 0.0
        self._echecs_reseau = 0
        self._empreinte_cle = ""
        self.dernier_genre = ""
        self.appels_api = 0

    @property
    def voix(self):                                      # utilise par la cle de cache de jarvis14.dire()
        return cfg.voice_id() or "?"

    def disponible(self):
        return bool(cfg.cle_api())

    # ------------------------------------------------------------------ statut
    def _statut(self, statut, genre=""):
        self.dernier_genre = genre
        if ETAT.voix != statut:
            ETAT.definir(voix=statut)
            try:
                from modes.ghost_protocol import hud_bridge
                hud_bridge.voix(statut, genre)
            except Exception:
                pass

    def _bloquer(self, genre):
        base = DELAIS.get(genre, 120)
        if genre in ("reseau", "timeout"):
            self._echecs_reseau += 1
            base = min(DELAI_MAX_RESEAU, base * (2 ** (self._echecs_reseau - 1)))   # reessais espaces, bornes
        self._bloque_jusqua = self._horloge() + base
        LOG.warning("Ghost voice : ElevenLabs indisponible (%s) -> voix Windows ~%d s, reessai automatique", genre, base)
        self._statut(VOIX_FALLBACK, genre)

    # ------------------------------------------------------------------ synthese
    def synthetiser(self, texte):
        try:
            return self._synthetiser(texte)
        except Exception:                                # la voix ne doit JAMAIS faire tomber Jarvis
            LOG.exception("Ghost voice : erreur inattendue")
            self._statut(VOIX_FALLBACK, "inattendue")
            return None

    def _synthetiser(self, texte):
        t = preparer_texte(texte, cfg.max_caracteres())
        if t is None:
            return None                                   # message technique/vide : Windows, 0 caractere consomme
        cle = cfg.cle_api()
        if not cle:
            self._statut(VOIX_FALLBACK, "cle_absente")
            return None
        voix = cfg.voice_id()
        if not voix:
            self._statut(VOIX_FALLBACK, "voix_absente")
            return None
        empreinte = hashlib.sha256(cle.encode()).hexdigest()[:8]
        if empreinte != self._empreinte_cle:             # nouvelle cle saisie : on retente tout de suite
            self._empreinte_cle, self._bloque_jusqua, self._echecs_reseau = empreinte, 0.0, 0
        import numpy as np
        modele, reglages = cfg.model_id(), cfg.reglages_voix()
        ck = self.cache.cle(t, voix, modele, reglages)
        pcm = self.cache.lire(ck)
        if pcm is not None:                               # 1) cache : aucun appel, aucun caractere
            self.usage.ajouter(cache=True)
            if self._horloge() >= self._bloque_jusqua:
                self._statut(VOIX_ELEVENLABS)
            return np.frombuffer(pcm, dtype=np.int16), 24000
        if self._horloge() < self._bloque_jusqua:         # 2) disjoncteur ouvert
            self._statut(VOIX_FALLBACK, self.dernier_genre)
            return None
        plafond = cfg.quota_mensuel()
        if plafond and self.usage.caracteres + len(t) > plafond:
            self._statut(VOIX_FALLBACK, "plafond_local")
            return None
        try:
            audio = self._appeler(t, cle, voix, modele, reglages)
        except ErreurVoix as e:
            self._bloquer(e.genre)
            return None
        self.cache.ecrire(ck, audio.tobytes())
        self.usage.ajouter(len(t))
        if self._budget:
            try:
                from core import budget
                budget.enregistrer_tts(len(t))
            except Exception:
                pass
        self._echecs_reseau = 0
        self._statut(VOIX_ELEVENLABS)
        return audio, 24000

    def _appeler(self, texte, cle, voix, modele, reglages):
        mp3 = False
        if self._decodeur is None:
            try:
                import miniaudio  # noqa: F401
                mp3 = True
            except ImportError:
                mp3 = False
        url = URL_TTS.format(voice=voix) + ("" if mp3 else "?output_format=pcm_24000")
        charge = {"text": texte, "model_id": modele, "voice_settings": reglages}
        if any(x in modele for x in ("flash", "turbo")):
            charge["language_code"] = cfg.langue()
        entetes = {"xi-api-key": cle, "Content-Type": "application/json",
                   "Accept": "audio/mpeg" if mp3 else "audio/pcm"}
        self.appels_api += 1
        statut, corps = self._http(url, json.dumps(charge).encode("utf-8"), entetes, cfg.timeout_s())
        if statut != 200:
            raise ErreurVoix(classer_http(statut, corps), f"HTTP {statut}")
        if not corps:
            raise ErreurVoix("generation", "audio vide")
        try:
            audio = self._decodeur(corps) if self._decodeur else _decoder(corps, mp3)
        except Exception as e:                           # audio illisible
            raise ErreurVoix("generation", f"decodage : {type(e).__name__}") from None
        if audio is None or len(audio) == 0:
            raise ErreurVoix("generation", "audio vide")
        return audio
