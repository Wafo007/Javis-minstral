"""Detection du mot d'activation « Jarvis » sans onnxruntime (donc sans Visual C++).

Deux moteurs, meme interface que openwakeword.Model :
    predict(int16[1280]) -> {"jarvis": score 0..1}      reset()

* "whisper"      : detection de parole (energie) -> mini Whisper (tiny, int8, CPU,
                   ~75 Mo) sur les segments de voix -> recherche du mot « Jarvis ».
                   Tourne dans un thread : la boucle micro n'est jamais bloquee.
* "openwakeword" : ancien moteur (necessite onnxruntime).
* "auto" (defaut): openwakeword s'il s'importe, sinon whisper.

Config (config.yaml) :
    wake:
      moteur: auto            # auto | whisper | openwakeword
      whisper_modele: tiny    # tiny (rapide) | base (plus fiable)
"""
from __future__ import annotations

import difflib
import queue
import re
import threading
import unicodedata
from collections import deque
from pathlib import Path

import numpy as np

TAUX = 16000
BLOC = 1280                      # 80 ms
_CIBLE = "jarvis"
_VARIANTES = {"jarvis", "jarvice", "jarvys", "jarviss", "djarvis", "jarvi", "garvis",
              "charvis", "harvis", "jarvisse", "yarvis", "darvis"}


def _norm(txt: str) -> str:
    txt = unicodedata.normalize("NFD", txt.lower())
    return "".join(c for c in txt if unicodedata.category(c) != "Mn")


def score_jarvis(texte: str) -> float:
    """0..1 : confiance que le texte transcrit contient « Jarvis »."""
    meilleur = 0.0
    for mot in re.findall(r"[a-z]+", _norm(texte)):
        if mot in _VARIANTES:
            return 1.0
        if 5 <= len(mot) <= 8:
            r = difflib.SequenceMatcher(None, mot, _CIBLE).ratio()
            if r >= 0.78:
                meilleur = max(meilleur, r)
    return meilleur


class WakeWhisper:
    def __init__(self, modele: str = "tiny", transcrire=None):
        self._lock = threading.Lock()
        self._score = 0.0
        self._file: "queue.Queue" = queue.Queue(maxsize=3)
        self._transcrire = transcrire or self._charger(modele)
        self._init_etat()
        threading.Thread(target=self._travail, daemon=True, name="wake-whisper").start()

    @staticmethod
    def _charger(nom):
        from faster_whisper import WhisperModel
        m = WhisperModel(nom, device="cpu", compute_type="int8", cpu_threads=2)

        def f(audio):
            segs, _ = m.transcribe(audio, language="fr", beam_size=1, vad_filter=False,
                                   condition_on_previous_text=False,
                                   initial_prompt="Jarvis, Hey Jarvis.")
            return " ".join(s.text for s in segs)
        return f

    def _init_etat(self):
        self._pre = deque(maxlen=3)      # 240 ms avant la parole
        self._seg: list = []
        self._silence = 0
        self._bruit = 0.005

    # --- API openwakeword -------------------------------------------------
    def predict(self, pcm16) -> dict:
        bloc = np.asarray(pcm16, dtype=np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(bloc ** 2))) if bloc.size else 0.0
        parole = rms > max(0.012, 3.0 * self._bruit)
        if not parole and not self._seg:
            self._bruit = 0.95 * self._bruit + 0.05 * rms
        if parole:
            if not self._seg:
                self._seg = list(self._pre)
            self._seg.append(bloc)
            self._silence = 0
        elif self._seg:
            self._seg.append(bloc)
            self._silence += 1
        else:
            self._pre.append(bloc)
        if self._seg:
            n = len(self._seg)
            if (self._silence >= 4 and n >= 7) or n >= 25:       # fin de mot / 2 s max
                audio = np.concatenate(self._seg)
                garder = self._seg[-6:] if n >= 25 else []       # recouvrement 0,5 s
                self._seg, self._silence = list(garder), 0
                try:
                    self._file.put_nowait(audio)
                except queue.Full:
                    pass
            elif self._silence >= 4:                             # bruit bref : on jette
                self._seg, self._silence = [], 0
        with self._lock:
            s = self._score
            self._score = 0.0
        return {_CIBLE: s}

    def reset(self):
        with self._lock:
            self._score = 0.0
        while not self._file.empty():
            try:
                self._file.get_nowait()
            except queue.Empty:
                break
        self._init_etat()

    # --- thread de transcription ------------------------------------------
    def _travail(self):
        while True:
            audio = self._file.get()
            try:
                s = score_jarvis(self._transcrire(audio))
            except Exception:
                continue
            if s > 0:
                with self._lock:
                    self._score = max(self._score, 0.6 + 0.4 * s)


class WakeVosk:
    """Wake word via Vosk (Kaldi, DLL MinGW embarquees : aucun Visual C++ requis).
    Modele FR leger (~41 Mo) telecharge automatiquement une fois (~/.cache/vosk)."""

    def __init__(self, nom_modele: str = "vosk-model-small-fr-0.22", lang: str = "fr"):
        import json
        from vosk import KaldiRecognizer
        from core.transcription import vosk_modele
        self._model = vosk_modele(nom_modele)   # partage avec la transcription (1 seul chargement)
        self._json, self._Rec = json, KaldiRecognizer
        try:                      # si "jarvis" est dans le vocabulaire : grammaire restreinte (precis)
            self._grammaire = self._model.vosk_model_find_word("jarvis") >= 0
        except Exception:
            self._grammaire = False
        self._rec = self._nouveau()

    def _nouveau(self):
        if self._grammaire:
            return self._Rec(self._model, TAUX, '["jarvis", "hey jarvis", "[unk]"]')
        return self._Rec(self._model, TAUX)

    def predict(self, pcm16) -> dict:
        data = np.asarray(pcm16, dtype=np.int16).tobytes()
        if self._rec.AcceptWaveform(data):
            texte = self._json.loads(self._rec.Result()).get("text", "")
        else:
            texte = self._json.loads(self._rec.PartialResult()).get("partial", "")
        s = score_jarvis(texte)
        if s > 0:
            self._rec = self._nouveau()
            # mot exact = 0.95 (reveil ET interruption) ; variante floue = 0.55 (reveil seulement),
            # pour que l'echo de la voix de Jarvis ne le coupe pas lui-meme.
            return {_CIBLE: 0.95 if s >= 1.0 else 0.55}
        return {_CIBLE: 0.0}

    def reset(self):
        self._rec = self._nouveau()


def creer_reveil(moteur: str = "auto", modele_whisper: str = "tiny", modele_vosk: str = "vosk-model-small-fr-0.22"):
    """Renvoie (objet_reveil, nom_du_moteur). auto : openwakeword -> vosk -> whisper."""
    moteur = (moteur or "auto").lower()
    essais = {"auto": ["openwakeword", "vosk", "whisper"]}.get(moteur, [moteur])
    erreurs = []
    for nom in essais:
        try:
            if nom == "openwakeword":
                import openwakeword
                from openwakeword.model import Model
                obj = Model(wakeword_model_paths=[str(
                    Path(openwakeword.__file__).parent / "resources" / "models" / "hey_jarvis_v0.1.onnx")])
                obj.nom_moteur = nom
                return obj, nom
            if nom in ("vosk", "whisper"):
                obj = WakeVosk(modele_vosk) if nom == "vosk" else WakeWhisper(modele_whisper)
                obj.nom_moteur = nom
                return obj, nom
            raise ValueError(f"wake.moteur inconnu : {nom}")
        except Exception as e:                       # ImportError/OSError DLL, modele absent...
            erreurs.append(f"{nom}: {type(e).__name__}: {e}")
            print(f"  [wake] moteur {nom} indisponible ({type(e).__name__}).")
    raise RuntimeError("Aucun moteur de wake word disponible :\n  " + "\n  ".join(erreurs))
