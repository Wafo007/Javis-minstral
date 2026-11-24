"""Journal d'audit detaille (JSONL, horodate, secrets masques) et arret d'urgence."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from modes.ghost_protocol.security.modele import masquer


class ArretUrgence:
    """Interrupteur d'arret d'urgence : un Event + un fichier drapeau (arret meme depuis un autre processus)."""

    def __init__(self, fichier: Path | None = None):
        self._event = threading.Event()
        self.fichier = Path(fichier) if fichier else None

    def declencher(self, motif: str = "arret d'urgence"):
        self.motif = motif
        self._event.set()
        if self.fichier:
            try:
                self.fichier.parent.mkdir(parents=True, exist_ok=True)
                self.fichier.write_text(f"{time.time()} {motif}\n", encoding="utf-8")
            except OSError:
                pass

    def actif(self) -> bool:
        if self._event.is_set():
            return True
        if self.fichier and self.fichier.exists():
            self._event.set()
            return True
        return False

    def reinitialiser(self):
        self._event.clear()
        if self.fichier:
            try:
                self.fichier.unlink()
            except OSError:
                pass

    def attendre(self, delai: float) -> bool:
        """Dort jusqu'a `delai` secondes ; True si l'arret a ete declenche entre-temps."""
        fin = time.time() + delai
        while time.time() < fin:
            if self.actif():
                return True
            self._event.wait(min(0.1, max(0.0, fin - time.time())))
        return self.actif()


class Journal:
    def __init__(self, fichier: Path | None = None):
        self.fichier = Path(fichier) if fichier else None
        self._verrou = threading.Lock()
        self.lignes: list[dict] = []

    def ecrire(self, evenement: str, **champs):
        ligne = {"t": round(time.time(), 3), "evenement": evenement,
                 **{k: (masquer(v, 500) if isinstance(v, str) else v) for k, v in champs.items()}}
        with self._verrou:
            self.lignes.append(ligne)
            del self.lignes[:-5000]
            if self.fichier:
                try:
                    self.fichier.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.fichier, "a", encoding="utf-8") as f:
                        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
                except OSError:
                    pass
        return ligne
