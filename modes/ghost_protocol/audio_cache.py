"""Cache disque des phrases deja synthetisees (PCM 16 bits mono 24 kHz) : jamais deux fois le meme audio facture."""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path

LOG = logging.getLogger("jarvis.ghost")


class CacheAudio:
    def __init__(self, dossier, max_octets=50 * 1024 * 1024):
        self.dossier = Path(dossier)
        self.max_octets = int(max_octets)
        self._verrou = threading.Lock()
        self.succes = 0
        self.echecs = 0

    @staticmethod
    def cle(texte: str, voix: str, modele: str, reglages: dict) -> str:
        brut = "|".join([voix, modele, repr(sorted((reglages or {}).items())), " ".join(str(texte).split())])
        return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:40]

    def _chemin(self, cle):
        return self.dossier / f"{cle}.pcm"

    def lire(self, cle):
        f = self._chemin(cle)
        try:
            donnees = f.read_bytes()
        except OSError:
            self.echecs += 1
            return None
        if not donnees or len(donnees) % 2:
            self.echecs += 1
            return None
        try:
            os.utime(f, None)                          # « utilise recemment » pour l'eviction
        except OSError:
            pass
        self.succes += 1
        return donnees

    def ecrire(self, cle, pcm: bytes):
        if not pcm:
            return
        with self._verrou:
            try:
                self.dossier.mkdir(parents=True, exist_ok=True)
                tmp = self._chemin(cle).with_suffix(".tmp")
                tmp.write_bytes(pcm)
                tmp.replace(self._chemin(cle))
                self._purger()
            except OSError:
                LOG.warning("cache audio Ghost : ecriture impossible", exc_info=True)

    def _purger(self):
        fichiers = sorted(self.dossier.glob("*.pcm"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in fichiers)
        while fichiers and total > self.max_octets:
            p = fichiers.pop(0)
            total -= p.stat().st_size
            try:
                p.unlink()
            except OSError:
                pass

    def vider(self):
        for p in self.dossier.glob("*.pcm"):
            try:
                p.unlink()
            except OSError:
                pass
