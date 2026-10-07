"""Reconnaissance vocale : faster-whisper en local, repli cloud quand il est absent.

faster-whisper repose sur CTranslate2, qui n'existe pas sur toutes les plateformes
(notamment Windows ARM64 / Snapdragon). Dans ce cas, et seulement si la
configuration l'autorise, la transcription passe par l'API OpenAI avec la meme
interface que Whisper : ``modele.transcribe(audio, language="fr", ...)`` renvoie
``(segments, info)``, chaque segment ayant un attribut ``text``.

Regles du repli cloud :
  - ``stt.moteur`` : "auto" (defaut : local, sinon cloud), "local" (jamais de
    cloud) ou "openai" (cloud meme si Whisper local est installe) ;
  - jamais en mode de routage « local », qui promet zero appel d'API ;
  - il faut une cle ``openai.cle``. L'audio de la phrase part alors chez OpenAI ;
    le cout est compte dans le budget du jour.
"""
import io
import logging
import wave
from dataclasses import dataclass
from pathlib import Path

from core.config import reglage

LOG = logging.getLogger("jarvis.transcription")

TAUX = 16000
MESSAGE_INDISPONIBLE = (
    "Reconnaissance vocale indisponible : faster-whisper n'est pas installe sur cette "
    "machine (c'est le cas sur Windows ARM64) et le repli cloud n'est pas permis. "
    "Ajoute une cle openai.cle et garde stt.moteur sur auto, hors mode local.")


def whisper_local_disponible():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def moteur():
    choix = str(reglage("stt.moteur", "auto") or "auto").strip().lower()
    return choix if choix in {"auto", "local", "openai", "vosk", "mistral"} else "auto"


def cloud_autorise():
    """Vrai si l'audio peut partir chez OpenAI : moteur non local, routage non local, cle."""
    if moteur() == "local":
        return False
    try:
        from core.routage import mode_actuel
        if mode_actuel() == "local":
            return False
    except Exception:
        pass
    return bool(str(reglage("openai.cle", "") or "").strip())


@dataclass
class Segment:
    """Meme forme qu'un segment faster-whisper pour le code appelant."""
    text: str
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0


def _en_wav(audio):
    """(octets WAV 16 bits mono, duree en secondes) depuis un tableau 16 kHz ou un fichier."""
    if isinstance(audio, (str, Path)):
        donnees = Path(audio).read_bytes()
        try:
            with wave.open(io.BytesIO(donnees), "rb") as f:
                return donnees, f.getnframes() / float(f.getframerate() or TAUX)
        except Exception:
            return donnees, 0.0
    import numpy as np
    echantillons = np.asarray(audio)
    if echantillons.dtype != np.int16:
        echantillons = (np.clip(echantillons.astype(np.float32), -1.0, 1.0) * 32767).astype(np.int16)
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(TAUX)
        f.writeframes(echantillons.tobytes())
    return tampon.getvalue(), echantillons.size / float(TAUX)


class TranscripteurCloud:
    """Transcription par l'API OpenAI, interchangeable avec un modele faster-whisper."""

    nom = "OpenAI"

    def __init__(self, modele=None):
        self.modele = modele or str(reglage("stt.modele_cloud", "gpt-4o-mini-transcribe"))

    def transcribe(self, audio, language="fr", **_options):
        if not cloud_autorise():
            # Le mode local a pu etre active depuis le chargement : rien ne part.
            LOG.warning("transcription cloud refusee (mode local, stt.moteur ou cle absente)")
            return [], None
        donnees, secondes = _en_wav(audio)
        if 0.0 < secondes < 0.3:
            return [], None
        from core import cloud
        client = cloud.client_openai()
        if client is None:
            return [], None
        try:
            reponse = client.audio.transcriptions.create(
                model=self.modele, file=("phrase.wav", donnees, "audio/wav"), language=language)
        except Exception as e:      # cle invalide (401), reseau coupe... : repli local Vosk
            if not vosk_disponible():
                raise
            LOG.warning("transcription OpenAI en echec (%s) : repli Vosk local.", type(e).__name__)
            return TranscripteurVosk().transcribe(audio, language=language)
        texte = str(getattr(reponse, "text", "") or "").strip()
        try:
            from core import budget
            budget.enregistrer_stt(secondes, self.modele)
        except Exception:
            pass
        return ([Segment(texte)] if texte else []), None


_VOSK = {}


def vosk_modele(nom=None):
    """Modele Vosk partage (wake word + transcription) : charge une seule fois."""
    nom = nom or str(reglage("stt.vosk_modele", "vosk-model-small-fr-0.22"))
    if nom not in _VOSK:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        _VOSK[nom] = Model(model_path=nom) if Path(nom).is_dir() else Model(model_name=nom)
    return _VOSK[nom]


def vosk_disponible():
    try:
        import vosk  # noqa: F401
        return True
    except Exception:
        return False


class TranscripteurVosk:
    """Transcription 100 % locale par Vosk (aucun Visual C++, aucune cle API)."""

    nom = "Vosk"

    def __init__(self, nom_modele=None):
        self._modele = vosk_modele(nom_modele)

    def transcribe(self, audio, language="fr", **_options):
        import json
        import numpy as np
        from vosk import KaldiRecognizer
        if isinstance(audio, (str, Path)):
            with wave.open(str(audio), "rb") as f:
                pcm = f.readframes(f.getnframes())
                taux = f.getframerate() or TAUX
                if f.getnchannels() == 2:
                    pcm = np.frombuffer(pcm, np.int16).reshape(-1, 2).mean(axis=1).astype(np.int16).tobytes()
        else:
            a = np.asarray(audio)
            if a.dtype != np.int16:
                a = (np.clip(a.astype(np.float32), -1.0, 1.0) * 32767).astype(np.int16)
            pcm, taux = a.tobytes(), TAUX
        if len(pcm) < 2 * 0.3 * taux:
            return [], None
        rec = KaldiRecognizer(self._modele, taux)
        for i in range(0, len(pcm), 8000):
            rec.AcceptWaveform(pcm[i:i + 8000])
        texte = str(json.loads(rec.FinalResult()).get("text", "")).strip()
        return ([Segment(texte)] if texte else []), None


def mistral_autorise():
    """Vrai si l'audio peut partir chez Mistral : moteur non local, routage non local, cle."""
    if moteur() == "local":
        return False
    try:
        from core.routage import mode_actuel
        if mode_actuel() == "local":
            return False
    except Exception:
        pass
    return bool(str(reglage("mistral.cle", "") or "").strip())


class TranscripteurMistral:
    """Transcription par l'API Mistral (Voxtral, gratuit sur le plan Free dans ses limites).
    Si l'appel echoue (cle refusee, quota, reseau) et que Vosk est installe : repli local."""

    nom = "Mistral (Voxtral)"

    def __init__(self, modele=None):
        self.modele = modele or str(reglage("stt.modele_mistral", "voxtral-mini-latest"))
        self._vosk = None

    def transcribe(self, audio, language="fr", **options):
        donnees, secondes = _en_wav(audio)
        if 0.0 < secondes < 0.3:
            return [], None
        try:
            from core import cloud
            client = cloud.client_mistral()
            if client is None:
                raise RuntimeError("mistral.cle absente")
            reponse = client.audio.transcriptions.create(
                model=self.modele, file=("phrase.wav", donnees, "audio/wav"), language=language)
            texte = str(getattr(reponse, "text", "") or "").strip()
            # Voxtral invente parfois du texte (espagnol, hindi...) sur du bruit/de l'echo.
            if any((ord(c) > 0x24F and c not in "\u2019\u2018\u201c\u201d\u00ab\u00bb\u2026\u2013\u2014\u20ac\u0153\u0152")
                   or c in "\u00bf\u00a1" for c in texte):
                LOG.info("transcription Mistral ignoree (hors francais) : %s", texte)
                texte = ""
        except Exception as e:
            LOG.warning("transcription Mistral en echec (%s : %s)", type(e).__name__, e)
            if not vosk_disponible():
                raise
            if self._vosk is None:
                self._vosk = TranscripteurVosk()
            return self._vosk.transcribe(audio, language=language)
        try:
            from core import budget
            budget.enregistrer_stt(secondes, self.modele, "Mistral transcription")
        except Exception:
            pass
        return ([Segment(texte)] if texte else []), None


def choisir_transcripteur_distant():
    """Transcripteur hors faster-whisper (Mistral > Vosk > OpenAI) ou None.
    stt.moteur : mistral | vosk | auto (auto : seulement si Whisper local est absent)."""
    m = moteur()
    if m == "mistral" and mistral_autorise():
        return TranscripteurMistral()
    if m == "vosk" and vosk_disponible():
        return TranscripteurVosk()
    if m == "auto" and not whisper_local_disponible():
        if mistral_autorise():
            return TranscripteurMistral()
        if cloud_autorise():
            return TranscripteurCloud()
        if vosk_disponible():
            return TranscripteurVosk()
    return None


def repli_cloud(raison=""):
    """Transcripteur cloud si le repli est permis, sinon None (avec un message clair)."""
    if moteur() != "local" and cloud_autorise():
        LOG.warning("Whisper local indisponible%s : transcription par OpenAI.",
                    f" ({raison})" if raison else "")
        return TranscripteurCloud()
    LOG.error(MESSAGE_INDISPONIBLE)
    return None


def charger(nom, device="cpu", compute_type="int8"):
    """Modele de transcription : faster-whisper si possible, sinon repli cloud, sinon None."""
    if moteur() == "openai" and cloud_autorise():
        return TranscripteurCloud()
    distant = choisir_transcripteur_distant()
    if distant is not None:
        return distant
    if not whisper_local_disponible():
        return repli_cloud("faster-whisper absent")
    from faster_whisper import WhisperModel
    return WhisperModel(nom, device=device, compute_type=compute_type)
