"""Tests de l'arbitrage entre micros, sans matériel audio."""
import threading
import time
import unittest

from core.arbitrage_micro import ArbitreMicro


class ArbitrageMicroTests(unittest.TestCase):
    def test_le_meilleur_score_est_le_seul_accepte(self):
        arbitre = ArbitreMicro(fenetre=0.03, verrou=0.2)
        resultats = {}

        def reserver(nom, score):
            resultats[nom] = arbitre.reserver(nom, score)

        faible = threading.Thread(target=reserver, args=("bureau", 0.62))
        fort = threading.Thread(target=reserver, args=("cuisine", 0.91))
        faible.start()
        time.sleep(0.005)
        fort.start()
        faible.join()
        fort.join()

        self.assertFalse(resultats["bureau"])
        self.assertTrue(resultats["cuisine"])

    def test_le_verrou_refuse_un_autre_micro(self):
        arbitre = ArbitreMicro(fenetre=0.0, verrou=0.2)
        self.assertTrue(arbitre.reserver("bureau", 0.7))
        self.assertFalse(arbitre.reserver("cuisine", 0.99))


if __name__ == "__main__":
    unittest.main()
