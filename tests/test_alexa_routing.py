"""Tests du routage Alexa déterministe, sans connexion à Amazon."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from tools.alexa import (_analyser_commande, _appareil, _routine,
                         alexa_appareil, alexa_routine)


class AlexaRoutingTests(unittest.TestCase):
    def test_lumieres_du_salon_passent_par_alexa(self):
        self.assertEqual(
            _analyser_commande("Allume les lumières du salon"),
            ("alexa_appareil", {"appareil": "lumieres salon", "action": "allumer"}),
        )

    def test_extinction_clim(self):
        self.assertEqual(
            _analyser_commande("Éteins la clim"),
            ("alexa_appareil", {"appareil": "clim", "action": "eteindre"}),
        )

    def test_piece_du_satellite_complete_une_lumiere_sans_piece(self):
        self.assertEqual(
            _analyser_commande("Allume la lumière", piece="cuisine"),
            ("alexa_appareil", {"appareil": "lumiere cuisine", "action": "allumer"}),
        )

    def test_piece_dite_gagne_sur_la_piece_du_satellite(self):
        self.assertEqual(
            _analyser_commande("Allume les lumières du salon", piece="cuisine"),
            ("alexa_appareil", {"appareil": "lumieres salon", "action": "allumer"}),
        )

    def test_lumiere_de_la_piece_amaran_reste_locale(self):
        self.assertIsNone(_analyser_commande(
            "Allume la lumière du bureau", piece_amaran="bureau"))
        self.assertEqual(
            _analyser_commande(
                "Allume la lumière du bureau sur Alexa", piece_amaran="bureau"),
            ("alexa_appareil", {"appareil": "lumiere bureau", "action": "allumer"}),
        )

    def test_routine_explicite(self):
        self.assertEqual(
            _analyser_commande("Lance la routine bonne nuit"),
            ("alexa_routine", {"nom": "bonne nuit"}),
        )

    def test_routine_explicite_avec_formulation_naturelle(self):
        self.assertEqual(
            _analyser_commande("Peux-tu lancer la routine bonne nuit"),
            ("alexa_routine", {"nom": "bonne nuit"}),
        )
        self.assertEqual(
            _analyser_commande("Je voudrais que tu lances ma routine bonne nuit"),
            ("alexa_routine", {"nom": "bonne nuit"}),
        )

    def test_discussion_sur_les_routines_n_est_pas_executee(self):
        self.assertIsNone(_analyser_commande(
            "Je ne t'ai pas demandé de faire une routine, je parlais d'Alexa"))
        self.assertIsNone(_analyser_commande(
            "En gros je voudrais faire une routine dans une vidéo sur Alexa"))

    def test_question_sur_alexa_n_allume_rien(self):
        self.assertIsNone(_analyser_commande(
            "J'aimerais savoir si Alexa peut allumer les lumières du salon"))

    def test_demande_polie_reste_une_commande(self):
        self.assertEqual(
            _analyser_commande("Peux-tu allumer les lumières du salon"),
            ("alexa_appareil", {"appareil": "lumieres salon", "action": "allumer"}),
        )

    def test_variantes_naturelles_domotiques(self):
        cas = {
            "Tu pourrais rallumer la clim": (
                "alexa_appareil", {"appareil": "clim", "action": "allumer"}),
            "Demande à Alexa d'éteindre la clim": (
                "alexa_appareil", {"appareil": "clim", "action": "eteindre"}),
            "Mets la clim en marche": (
                "alexa_appareil", {"appareil": "clim", "action": "allumer"}),
            "Mets en route la clim": (
                "alexa_appareil", {"appareil": "clim", "action": "allumer"}),
            "Passe les lumières sur off": (
                "alexa_appareil", {"appareil": "lumieres", "action": "eteindre"}),
        }
        for phrase, attendu in cas.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(_analyser_commande(phrase), attendu)

    def test_nom_de_routine_precharge(self):
        automations = [{"name": "Que la lumière soit", "triggers": []}]
        self.assertEqual(
            _analyser_commande("Que la lumière soit", automations=automations),
            ("alexa_routine", {"nom": "Que la lumière soit"}),
        )

    def test_commandes_non_domotiques_ne_sont_pas_detournees(self):
        self.assertIsNone(_analyser_commande("Ouvre Chrome"))
        self.assertIsNone(_analyser_commande("Arrête la musique"))
        self.assertIsNone(_analyser_commande("N'allume pas la lumière"))

    def test_echec_routine_ne_liste_pas_les_routines_privees(self):
        autos = [{"name": "Routine privée du salon", "triggers": []}]
        with patch("tools.alexa._assurer_login", new=AsyncMock(return_value=object())), \
                patch("tools.alexa._automations", new=AsyncMock(return_value=autos)):
            message = asyncio.run(_routine("routine inconnue"))
        self.assertIn("Je ne trouve pas", message)
        self.assertNotIn("Routine privée du salon", message)
        self.assertNotIn("Tes routines", message)

    def test_echec_appareil_ne_liste_pas_les_routines_privees(self):
        autos = [{"name": "Routine privée du salon", "triggers": []}]
        with patch("tools.alexa._assurer_login", new=AsyncMock(return_value=object())), \
                patch("tools.alexa._automations", new=AsyncMock(return_value=autos)):
            message = asyncio.run(_appareil("lampe cuisine", "allumer"))
        self.assertIn("Je ne trouve pas", message)
        self.assertNotIn("Routine privée du salon", message)
        self.assertNotIn("Tes routines", message)

    def test_outils_refusent_une_phrase_de_discussion_du_modele(self):
        message = alexa_routine(
            "en gros je t ai dit que j aimerais faire une video sur alexa")
        self.assertIn("rien déclenché", message)
        message = alexa_appareil(
            "reprendre episode simpsons en mode je voudrais faire une video", "allumer")
        self.assertIn("rien déclenché", message)


if __name__ == "__main__":
    unittest.main()
