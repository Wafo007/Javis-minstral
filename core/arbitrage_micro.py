"""Arbitrage du mot d'activation entre le micro principal et les satellites.

Quand plusieurs micros entendent le même « Hey Jarvis », ils déposent leur score
openWakeWord pendant une fenêtre très courte. Seule la source au meilleur score
obtient le droit de biper, capturer et répondre.
"""
import math
import threading
import time

from core.config import reglage


class ArbitreMicro:
    def __init__(self, fenetre=0.18, verrou=4.0):
        self.fenetre = max(0.0, float(fenetre))
        self.verrou = max(0.1, float(verrou))
        self._condition = threading.Condition()
        self._tour = None
        self._proprietaire = None
        self._verrou_jusqua = 0.0

    def reserver(self, source, score):
        """Renvoie True à la source retenue, False aux micros concurrents."""
        source = str(source or "micro")
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        if not math.isfinite(score):
            score = 0.0

        with self._condition:
            maintenant = time.monotonic()
            if maintenant < self._verrou_jusqua and self._proprietaire:
                return self._proprietaire == source

            if self._tour is None:
                self._tour = {
                    "echeance": maintenant + self.fenetre,
                    "candidats": {},
                    "gagnant": None,
                }
            tour = self._tour
            precedent = tour["candidats"].get(source)
            if precedent is None or score > precedent[0]:
                tour["candidats"][source] = (score, maintenant)
            self._condition.notify_all()

            while tour["gagnant"] is None:
                restant = tour["echeance"] - time.monotonic()
                if restant > 0:
                    self._condition.wait(timeout=restant)
                    continue
                # Score le plus fort ; à égalité, le premier micro détecté gagne.
                tour["gagnant"] = max(
                    tour["candidats"],
                    key=lambda nom: (
                        tour["candidats"][nom][0],
                        -tour["candidats"][nom][1],
                    ),
                )
                self._proprietaire = tour["gagnant"]
                self._verrou_jusqua = time.monotonic() + self.verrou
                if self._tour is tour:
                    self._tour = None
                self._condition.notify_all()
            return tour["gagnant"] == source

    def reinitialiser(self):
        """Réinitialisation explicite, principalement utile aux tests."""
        with self._condition:
            self._tour = None
            self._proprietaire = None
            self._verrou_jusqua = 0.0
            self._condition.notify_all()


_ARBITRE = ArbitreMicro(
    fenetre=reglage("assistant.arbitrage_fenetre", 0.18),
    verrou=reglage("assistant.arbitrage_verrou", 4.0),
)


def reserver_reveil(source, score):
    """Point d'entrée commun au micro Windows et aux satellites."""
    if not bool(reglage("assistant.arbitrage_micro", True)):
        return True
    return _ARBITRE.reserver(source, score)
