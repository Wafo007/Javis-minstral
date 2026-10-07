"""Tests des garde-fous appliqués aux textes et journaux locaux."""
import unittest

from core.confidentialite import caviarder, filtrer


class ConfidentialiteTests(unittest.TestCase):
    def test_caviarder_preserve_la_mise_en_forme(self):
        cle_factice = "sk-" + "a" * 20
        texte = f"Contact: test@example.com\nToken: {cle_factice}"
        resultat = caviarder(texte)
        self.assertIn("\n", resultat)
        self.assertNotIn("test@example.com", resultat)
        self.assertNotIn(cle_factice, resultat)
        self.assertIn("[adresse mail]", resultat)
        self.assertIn("[cle]", resultat)

    def test_filtrer_reste_court_pour_la_voix(self):
        self.assertLessEqual(len(filtrer("mot " * 100, 40)), 43)


if __name__ == "__main__":
    unittest.main()
