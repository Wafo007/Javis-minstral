"""S5 : operations sur fichiers confinees, atomiques, verifiees ; suppression recuperable et N3."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import registre
from tools import fichiers


class TestFichiers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self._tmp.name).resolve() / "Jarvis"
        self.racine.mkdir()
        self._p = patch.object(fichiers, "racines", return_value=[self.racine])
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def test_scenario_complet_creer_modifier_deplacer_lire_supprimer(self):
        """Critere S5 : creer, modifier, deplacer, lire puis supprimer un dossier de test."""
        r = fichiers.fichier_ecrire("test/notes.txt", "Bonjour, ça va ?\n")
        self.assertTrue(r.succes and r.verifie)
        r = fichiers.fichier_ecrire("test/notes.txt", "Suite.\n", ajouter=True)
        self.assertTrue(r.succes)
        self.assertEqual((self.racine / "test" / "notes.txt").read_text(encoding="utf-8"), "Bonjour, ça va ?\nSuite.\n")
        self.assertTrue((self.racine / "test" / "notes.txt.bak").exists())      # ancienne version sauvegardee
        r = fichiers.fichier_deplacer("test/notes.txt", "archive/notes2.txt")
        self.assertTrue(r.succes)
        self.assertFalse((self.racine / "test" / "notes.txt").exists())
        r = fichiers.fichier_lire("archive/notes2.txt")
        self.assertEqual(str(r), "Bonjour, ça va ?\nSuite.\n")
        r = fichiers.fichier_supprimer("archive")
        self.assertTrue(r.succes and r.verifie)
        self.assertFalse((self.racine / "archive").exists())
        corbeille = list((self.racine / fichiers.CORBEILLE).iterdir())
        self.assertEqual(len(corbeille), 1)                                      # recuperable
        self.assertTrue((corbeille[0] / "notes2.txt").exists())

    def test_confinement_et_evasions(self):
        for chemin in ("../hors.txt", "/etc/passwd", "a/../../hors.txt", "\\\\hote\\partage\\x.txt"):
            with self.subTest(chemin=chemin):
                r = fichiers.fichier_ecrire(chemin, "x")
                self.assertFalse(r.succes)
        self.assertFalse((self.racine.parent / "hors.txt").exists())

    def test_lien_symbolique_vers_l_exterieur_refuse(self):
        dehors = Path(self._tmp.name) / "dehors"
        dehors.mkdir()
        try:
            os.symlink(dehors, self.racine / "lien")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks indisponibles")
        r = fichiers.fichier_ecrire("lien/x.txt", "x")
        self.assertFalse(r.succes)
        self.assertFalse((dehors / "x.txt").exists())

    def test_fichiers_de_secrets_refuses(self):
        for nom in ("config.yaml", ".env", "id_rsa", "token.json"):
            self.assertFalse(fichiers.fichier_ecrire(nom, "x").succes, nom)

    def test_ecriture_atomique_pas_de_temporaire_residuel_ni_perte(self):
        fichiers.fichier_ecrire("a.txt", "v1")
        with patch.object(fichiers.os, "replace", side_effect=OSError("disque plein")):
            r = fichiers.fichier_ecrire("a.txt", "v2")
        self.assertFalse(r.succes)
        self.assertEqual((self.racine / "a.txt").read_text(encoding="utf-8"), "v1")     # rien n'est perdu
        self.assertEqual([p.name for p in self.racine.glob("*.tmp")], [])

    def test_deplacer_n_ecrase_pas(self):
        fichiers.fichier_ecrire("a.txt", "A")
        fichiers.fichier_ecrire("b.txt", "B")
        r = fichiers.fichier_deplacer("a.txt", "b.txt")
        self.assertFalse(r.succes)
        self.assertEqual((self.racine / "b.txt").read_text(encoding="utf-8"), "B")

    def test_supprimer_une_racine_est_refuse(self):
        self.assertFalse(fichiers.fichier_supprimer(".").succes)
        self.assertTrue(self.racine.exists())

    def test_fichier_inexistant_ou_binaire(self):
        self.assertEqual(fichiers.fichier_lire("zzz.txt").erreur, "introuvable")
        (self.racine / "b.bin").write_bytes(b"\xff\xfe\x00\x80")
        self.assertEqual(fichiers.fichier_lire("b.bin").erreur, "format")

    def test_permissions(self):
        registre.charger_outils()
        self.assertEqual(registre.niveau("fichier_lire"), "N1")
        self.assertEqual(registre.niveau("fichier_lister"), "N1")
        self.assertEqual(registre.niveau("fichier_ecrire"), "N2")
        self.assertEqual(registre.niveau("fichier_deplacer"), "N2")
        self.assertEqual(registre.niveau("fichier_supprimer"), "N3")     # jamais « toujours autoriser »
        self.assertFalse(registre.autoriser_toujours("fichier_supprimer"))
        for nom in ("fichier_lire", "fichier_ecrire", "fichier_deplacer", "fichier_supprimer", "fichier_lister"):
            self.assertFalse(registre.get(nom).mcp_expose, nom)
            self.assertNotIn(nom, [o.nom for o in registre.exposes_mcp()])


if __name__ == "__main__":
    unittest.main()
