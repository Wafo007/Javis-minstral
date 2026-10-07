"""Tests du registre local du Command Center Hermes, sans appel a Hermes."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import deleguer_a_hermes as hermes


class HermesTaskRegistryTests(unittest.TestCase):
    def test_session_auto_unique_et_persistance(self):
        with tempfile.TemporaryDirectory() as dossier:
            fichier = Path(dossier) / "taches.json"
            with patch.object(hermes, "_FICHIER_TACHES", fichier), \
                    patch.object(hermes, "_TACHES", []), \
                    patch.object(hermes, "_pousser_hud"):
                tache = hermes._ajouter_tache("", "Analyse le budget du mois")
                self.assertTrue(tache["session"].startswith("jarvis-analyse-le-budget"))
                hermes._finir_tache(tache, "terminee", resume="Fait",
                                    tokens=1234, cout=0.0123,
                                    modele="modele-test")
                stock = json.loads(fichier.read_text(encoding="utf-8"))
                self.assertEqual(stock[0]["statut"], "terminee")
                self.assertEqual(stock[0]["cout"], 0.0123)
                self.assertEqual(stock[0]["tokens"], 1234)

    def test_travail_de_creation_est_route_vers_hermes(self):
        tache = hermes.extraire_tache_contenu(
            "Écris-moi un script pour une vidéo sur mon Raspberry")
        self.assertIsNotNone(tache)
        self.assertIn("Écris-moi un script", tache)
        self.assertIn("Vault", tache)

        self.assertIsNotNone(hermes.extraire_tache_contenu(
            "Analyse mes créateurs de référence et propose trois hooks"))
        self.assertIsNotNone(hermes.extraire_tache_contenu(
            "Améliore cette accroche pour mon prochain Reel"))
        self.assertIsNotNone(hermes.extraire_tache_contenu(
            "Apprends à connaître mes créateurs et mes vidéos pour reprendre mon ton dans mes scripts"))

    def test_mentions_de_contenu_non_creatives_restent_chez_jarvis(self):
        self.assertIsNone(hermes.extraire_tache_contenu(
            "J'ai tourné ma vidéo hier"))
        self.assertIsNone(hermes.extraire_tache_contenu(
            "Quand je parle de scripts, faut-il passer par Hermes ?"))
        self.assertIsNone(hermes.extraire_tache_contenu(
            "Allume la lumière pour créer une vidéo"))
        self.assertIsNone(hermes.extraire_tache_contenu(
            "Où en est mon script ?"))

    def test_transport_auto_se_replie_sur_le_cli(self):
        attendu = ("Résultat Hermes", 10, 0.01, "modele-test")
        with patch.object(hermes, "_appeler_hermes_http",
                          side_effect=ConnectionError("API absente")), \
                patch.object(hermes, "_appeler_hermes_cli",
                             return_value=attendu) as cli, \
                patch.object(hermes, "reglage",
                             side_effect=lambda cle, defaut=None: (
                                 "auto" if cle == "hermes.transport" else defaut)):
            resultat = hermes._appeler_hermes("Écris un script")
        self.assertEqual(resultat, attendu)
        self.assertIn("Écris un script", cli.call_args.args[0])

    def test_transport_http_ne_masque_pas_une_erreur(self):
        with patch.object(hermes, "_appeler_hermes_http",
                          side_effect=RuntimeError("API cassée")), \
                patch.object(hermes, "_appeler_hermes_cli") as cli, \
                patch.object(hermes, "reglage",
                             side_effect=lambda cle, defaut=None: (
                                 "http" if cle == "hermes.transport" else defaut)):
            with self.assertRaisesRegex(RuntimeError, "API cassée"):
                hermes._appeler_hermes("Analyse")
        cli.assert_not_called()


if __name__ == "__main__":
    unittest.main()
