"""Auto-modification par la voix : outils, niveaux de permission, garde-fous (vrai git dans un depot temporaire)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import registre

registre.charger_outils()


def _git(d, *a):
    subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)


class MonCodeTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        _git(self.d, "init", "-q", "-b", "main")
        _git(self.d, "config", "user.email", "t@t.t")
        _git(self.d, "config", "user.name", "t")
        (self.d / "core").mkdir()
        (self.d / "core" / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.d / "config.yaml").write_text("cle: secret\n", encoding="utf-8")
        _git(self.d, "add", "core/a.py")
        _git(self.d, "commit", "-q", "-m", "init")
        from tools import mon_code
        self.m = mon_code
        p = patch.object(mon_code, "RACINE", self.d)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_niveaux_de_permission(self):
        self.assertEqual(registre.niveau("code_modification_enregistrer"), "N3")
        self.assertTrue(registre.get("code_modification_ecrire").confirmation)
        self.assertFalse(registre.get("code_modification_ecrire").mcp_expose)

    def test_secrets_illisibles_et_ineditables(self):
        self.assertFalse(self.m.code_lire("config.yaml").succes)
        self.m.code_modification_demarrer("essai")
        r = self.m.code_modification_ecrire("config.yaml", "cle: autre\n")
        self.assertFalse(r.succes)
        r = self.m.code_modification_ecrire("core/registre.py", "# verrou affaibli\n")
        self.assertFalse(r.succes)

    def test_cycle_complet_et_retour_arriere(self):
        self.assertIn("x = 1", self.m.code_lire("core/a.py"))
        self.assertTrue(self.m.code_modification_demarrer("essai").succes)
        self.assertTrue(self.m.code_modification_ecrire("core/a.py", "x = 2\n").succes)
        self.assertIn("+x = 2", self.m.code_modification_diff())
        # commit refuse tant que les tests n'ont pas ete lances
        self.assertFalse(self.m.code_modification_enregistrer("sans tests").succes)
        with patch.object(self.m.am, "COMMANDE_COMPILATION", ["python3", "-c", "pass"]), \
                patch.object(self.m.am, "COMMANDE_TESTS", ["python3", "-c", "pass"]):
            self.assertTrue(self.m.code_modification_tester().succes)
        self.assertTrue(self.m.code_modification_enregistrer("x vaut 2").succes)
        # la branche principale n'est PAS modifiee (aucune fusion)
        self.assertEqual((self.d / "core" / "a.py").read_text(encoding="utf-8"), "x = 1\n")

    def test_tests_rouges_empechent_le_commit_et_annuler_restaure(self):
        self.m.code_modification_demarrer("essai")
        self.m.code_modification_ecrire("core/a.py", "x = 3\n")
        with patch.object(self.m.am, "COMMANDE_COMPILATION", ["python3", "-c", "pass"]), \
                patch.object(self.m.am, "COMMANDE_TESTS", ["python3", "-c", "raise SystemExit(1)"]):
            self.assertFalse(self.m.code_modification_tester().succes)
        self.assertFalse(self.m.code_modification_enregistrer("non").succes)
        self.assertTrue(self.m.code_modification_annuler().succes)
        self.assertEqual((self.d / "core" / "a.py").read_text(encoding="utf-8"), "x = 1\n")


if __name__ == "__main__":
    unittest.main()
