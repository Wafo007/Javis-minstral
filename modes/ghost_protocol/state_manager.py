"""Etat du mode GHOST PROTOCOL : un seul objet, thread-safe, avec ecouteurs (HUD, consigne LLM...).

L'etat ne vit qu'en memoire : au redemarrage de Jarvis le mode est desactive (retour garanti au fonctionnement normal).
"""
from __future__ import annotations

import logging
import threading
import time

LOG = logging.getLogger("jarvis.ghost")

# Statuts du moteur vocal Ghost (affiches dans le HUD)
VOIX_ELEVENLABS = "ELEVENLABS"
VOIX_FALLBACK = "FALLBACK"          # ElevenLabs indisponible : voix Windows temporaire, reessais automatiques
VOIX_WINDOWS = "WINDOWS"            # voix Ghost coupee volontairement (ou mode inactif)
VOIX_INCONNUE = "EN ATTENTE"


class EtatGhost:
    def __init__(self):
        self._verrou = threading.RLock()
        self._ecouteurs = []
        self._reinitialiser_champs()

    def _reinitialiser_champs(self):
        self.actif = False
        self.depuis = None
        self.sortie_en_attente = False      # desactivation annoncee, finalisee apres la phrase d'adieu
        self.voix_coupee = False            # l'utilisatrice a coupe la voix ElevenLabs Ghost
        self.voix = VOIX_INCONNUE
        self.mission = ""
        self.etat_sim = "IDLE"              # IDLE | RUNNING | COMPLETED | ABORTED
        self.progression = 0.0
        self.menace = "-"
        self.script_genere = ""             # chemin du dernier script de demonstration

    def snapshot(self) -> dict:
        with self._verrou:
            return {"actif": self.actif, "mission": self.mission, "etat": self.etat_sim,
                    "progression": round(self.progression, 3), "menace": self.menace, "voix": self.voix,
                    "temps_s": int(time.time() - self.depuis) if self.depuis else 0,
                    "script": bool(self.script_genere)}

    def ecouter(self, fonction):
        """Enregistre fonction(snapshot) appelee apres chaque changement (hors verrou)."""
        with self._verrou:
            if fonction not in self._ecouteurs:
                self._ecouteurs.append(fonction)

    def oublier(self, fonction):
        with self._verrou:
            if fonction in self._ecouteurs:
                self._ecouteurs.remove(fonction)

    def definir(self, **champs):
        with self._verrou:
            for k, v in champs.items():
                if not hasattr(self, k):
                    raise AttributeError(k)
                setattr(self, k, v)
            ecouteurs, instantane = list(self._ecouteurs), self.snapshot()
        for f in ecouteurs:
            try:
                f(instantane)
            except Exception:
                LOG.exception("ecouteur d'etat Ghost")
        return instantane

    def remettre_a_zero(self):
        """Retour a l'etat normal ; conserve les ecouteurs."""
        with self._verrou:
            self._reinitialiser_champs()
            ecouteurs, instantane = list(self._ecouteurs), self.snapshot()
        for f in ecouteurs:
            try:
                f(instantane)
            except Exception:
                LOG.exception("ecouteur d'etat Ghost")


ETAT = EtatGhost()
