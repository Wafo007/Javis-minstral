"""Non-regression S3 (Playwright), S4 (Astra), S7 (Hermes), S9 (auto-modification) + bugs cloud.

Les appels reseau, LLM et Windows sont simules. Les tests git (S9) et le diagnostic Playwright
(S3, si Chromium est installe) sont REELS.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core import auto_modification as am
from core import cloud, playwright_partage
from tools import astra_pc
from tools import deleguer_a_hermes as hermes


# ------------------------------------------------------------------ cloud (regressions)
class TestCloudVisionRegression(unittest.TestCase):
    """UnboundLocalError introduit par le commit « gemini vision » : OpenAI/Anthropic plantaient."""

    def test_openai_ne_leve_plus_unboundlocalerror(self):
        item = SimpleNamespace(type="function_call", arguments='{"action": "termine"}')
        client = MagicMock()
        client.responses.create.return_value = SimpleNamespace(output=[item], usage=None)
        with patch.object(cloud, "client_openai", return_value=client), \
                patch.object(cloud, "enregistrer_usage"):
            r = cloud.decider_action_vision("s", "t", "AAAA", {}, nom_modele="gpt-6-astra",
                                            fournisseur_force="openai")
        self.assertEqual(r, {"action": "termine"})

    def test_anthropic_ne_leve_plus_unboundlocalerror(self):
        bloc = SimpleNamespace(type="tool_use", input={"action": "termine"})
        client = MagicMock()
        client.messages.create.return_value = SimpleNamespace(content=[bloc], usage=None)
        with patch.object(cloud, "client_anthropic", return_value=client), \
                patch.object(cloud, "enregistrer_usage"):
            r = cloud.decider_action_vision("s", "t", "AAAA", {}, nom_modele="claude-x",
                                            fournisseur_force="anthropic")
        self.assertEqual(r, {"action": "termine"})

    def _mistral(self, erreurs):
        class E(Exception):
            def __init__(self, code):
                self.status_code = code
        it = iter(erreurs)

        def create(**k):
            code = next(it)
            if code:
                raise E(code)
            call = SimpleNamespace(function=SimpleNamespace(arguments='{"action": "ok"}'))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))], usage=None)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def _reglage(self, secours):
        return lambda cle, defaut=None: secours if cle == "cloud.secours_actif" else defaut

    def test_mistral_toutes_les_erreurs_sans_secours_levent_la_derniere_erreur(self):
        client = self._mistral([500, 500, 500, 500])
        with patch.object(cloud, "fournisseur", return_value="mistral"), \
                patch.object(cloud, "client_mistral", return_value=client), \
                patch.object(cloud, "reglage", side_effect=self._reglage(False)), \
                patch.object(cloud, "enregistrer_usage"):
            with self.assertRaises(Exception) as ctx:            # PAS UnboundLocalError
                cloud.decider_action_vision("s", "t", "AAAA", {}, nom_modele="ministral-8b-latest")
        self.assertNotIsInstance(ctx.exception, UnboundLocalError)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 500)

    def test_mistral_429_avec_secours_bascule_sur_gemini(self):
        client = self._mistral([429])
        with patch.object(cloud, "fournisseur", return_value="mistral"), \
                patch.object(cloud, "client_mistral", return_value=client), \
                patch.object(cloud, "reglage", side_effect=self._reglage(True)), \
                patch.object(cloud, "_mistral_disponible", return_value=True), \
                patch.object(cloud, "_suspendre_mistral") as susp, \
                patch.object(cloud, "_decider_action_gemini", return_value={"action": "gemini"}) as gem:
            r = cloud.decider_action_vision("s", "t", "AAAA", {}, nom_modele="ministral-8b-latest")
        self.assertEqual(r, {"action": "gemini"})
        susp.assert_called_once()
        gem.assert_called_once()

    def test_mistral_erreur_non_secourable_est_propagee(self):
        client = self._mistral([401])
        with patch.object(cloud, "fournisseur", return_value="mistral"), \
                patch.object(cloud, "client_mistral", return_value=client), \
                patch.object(cloud, "reglage", side_effect=self._reglage(False)):
            with self.assertRaises(Exception) as ctx:
                cloud.decider_action_vision("s", "t", "AAAA", {}, nom_modele="ministral-8b-latest")
        self.assertEqual(ctx.exception.status_code, 401)


# ------------------------------------------------------------------ Astra (S4)
def _reglages(**v):
    return lambda cle, defaut=None: v.get(cle.split(".")[-1], defaut)


class TestAstraVerification(unittest.TestCase):
    def _run(self, decisions, captures, executer=None, verification=True):
        decider = MagicMock(side_effect=decisions)
        cap = MagicMock(side_effect=[{"image": {"data": c}} for c in captures])
        exec_ = executer or MagicMock(return_value="clic effectué")
        with patch.object(astra_pc.time, "sleep"), patch.object(astra_pc, "_echap_presse", return_value=False), \
                patch.object(astra_pc, "capture_screen", cap), \
                patch.object(astra_pc, "_executer_action", exec_), \
                patch.object(astra_pc, "_fournisseur_operateur", return_value="openai"), \
                patch.object(astra_pc.cloud, "decider_action_vision", decider), \
                patch.object(astra_pc, "reglage", side_effect=lambda cle, defaut=None: (
                    verification if cle == "astra_pc.verification_finale" else defaut)):
            return astra_pc.executer_controle("ouvre les parametres audio"), decider, exec_

    def test_termine_est_verifie_par_un_second_regard(self):
        res, decider, _ = self._run(
            [{"action": "cliquer", "x": 1, "y": 1}, {"action": "termine", "message": "Réglage ouvert."},
             {"accomplie": True, "constat": "la fenetre des reglages est visible"}],
            ["a", "b", "b"])
        self.assertEqual(res, "Réglage ouvert.")
        self.assertEqual(decider.call_count, 3)
        self.assertEqual(decider.call_args.kwargs["nom_outil"], "verifier_tache")

    def test_termine_non_confirme_n_est_pas_annonce_comme_reussi(self):
        res, decider, _ = self._run(
            [{"action": "termine", "message": "Fait."}, {"accomplie": False, "constat": "rien n'a change"},
             {"action": "termine", "message": "Fait."}, {"accomplie": False, "constat": "toujours rien"}],
            ["a", "a", "a", "a"])
        self.assertIn("Je n'ai pas pu confirmer", res)
        self.assertIn("toujours rien", res)
        self.assertNotEqual(res, "Fait.")

    def test_verification_indisponible_est_signalee(self):
        res, _, _ = self._run([{"action": "termine", "message": "Fait."}, RuntimeError("quota")], ["a", "a"])
        self.assertIn("pas pu verifier", res)

    def test_ecran_inchange_apres_trois_actions_arrete_la_boucle(self):
        action = {"action": "cliquer", "x": 5, "y": 5}
        res, decider, exec_ = self._run([action] * 6, ["x"] * 6)
        self.assertIn("aucun effet visible", res)
        self.assertLessEqual(exec_.call_count, 4)

    def test_actions_en_echec_repetees_arretent_la_boucle(self):
        action = {"action": "cliquer", "x": 5, "y": 5}
        exec_ = MagicMock(return_value="Ces coordonnees sont hors de l'image capturee.")
        res, _, _ = self._run([action] * 6, ["a", "b", "c", "d", "e", "f"], executer=exec_)
        self.assertIn("ont echoue", res)

    def test_cible_absente_erreur_propre(self):
        res, _, exec_ = self._run([{"action": "bloque", "raison": "le bouton n'est pas visible"}], ["a"])
        self.assertIn("le bouton n'est pas visible", res)
        exec_.assert_not_called()

    def test_garde_fous_conserves(self):
        self.assertIsNotNone(astra_pc._raison_blocage("tape mon mot de passe"))
        self.assertTrue(astra_pc.registre.get("controle_pc_astra").confirmation
                        if hasattr(astra_pc, "registre") else True)


# ------------------------------------------------------------------ Playwright (S3)
class TestPlaywrightPartage(unittest.TestCase):
    def setUp(self):
        playwright_partage._PW = None
        playwright_partage._FIL = None

    def tearDown(self):
        playwright_partage._PW = None
        playwright_partage._FIL = None

    def test_expliquer_erreur_greenlet(self):
        msg = playwright_partage.expliquer_erreur(ImportError("DLL load failed while importing _greenlet"))
        self.assertIn("greenlet", msg)
        self.assertIn("Visual C++", msg)

    def test_expliquer_erreur_chromium_absent(self):
        self.assertIn("playwright install chromium",
                      playwright_partage.expliquer_erreur(Exception("Executable doesn't exist at /x")))

    def test_appel_depuis_un_autre_thread_est_refuse_clairement(self):
        playwright_partage._PW = object()
        playwright_partage._FIL = -1
        with self.assertRaises(playwright_partage.PlaywrightIndisponible):
            playwright_partage.obtenir()

    def test_echec_du_demarrage_ne_laisse_pas_d_etat(self):
        faux = MagicMock()
        faux.sync_playwright.side_effect = ImportError("DLL load failed while importing _greenlet")
        with patch.dict(sys.modules, {"playwright": MagicMock(), "playwright.sync_api": faux}):
            with self.assertRaises(ImportError):
                playwright_partage.obtenir()
        self.assertIsNone(playwright_partage._PW)

    def test_diagnostic_ne_se_contente_pas_de_l_import(self):
        """L'import du paquet reussit mais _greenlet est casse : le diagnostic doit ECHOUER."""
        vrai_import = __import__

        def import_casse(nom, *a, **k):
            if nom == "greenlet":
                raise ImportError("DLL load failed while importing _greenlet")
            return vrai_import(nom, *a, **k)
        with patch("builtins.__import__", side_effect=import_casse):
            etapes = playwright_partage.diagnostiquer(lancer_navigateur=False)
        self.assertTrue(etapes[0][1])                                  # « import playwright » : OK
        echec = [e for e in etapes if not e[1]]
        self.assertTrue(echec)
        self.assertIn("greenlet", echec[0][2].lower())

    def test_diagnostic_reel_si_playwright_installe(self):
        try:
            import playwright  # noqa: F401
            import greenlet  # noqa: F401
        except ImportError:
            self.skipTest("playwright/greenlet absents")
        etapes = playwright_partage.diagnostiquer(lancer_navigateur=False)
        self.assertTrue(all(ok for _, ok, _ in etapes), etapes)
        self.assertEqual(etapes[-1][0], "demarrage du moteur")


# ------------------------------------------------------------------ Hermes (S7)
class TestHermesVerification(unittest.TestCase):
    def _deleguer(self, retour, livrable="", **kw):
        paroles, fins = [], []
        termine = threading.Event()

        def finir(t, statut, resume="", **k):
            fins.append((statut, resume))
            termine.set()

        class FauxFil:
            def __init__(self, target, **k):
                self.target = target

            def start(self):
                self.target()
        with tempfile.TemporaryDirectory() as d, \
                patch.object(hermes, "_FICHIER_TACHES", Path(d) / "t.json"), \
                patch.object(hermes, "_TACHES", []), patch.object(hermes, "_pousser_hud"), \
                patch.object(hermes, "_maj_tokens"), patch.object(hermes, "_journaliser"), \
                patch.object(hermes.threading, "Thread", FauxFil), \
                patch.object(hermes, "_finir_tache", side_effect=finir), \
                patch.object(hermes.voix, "parler", side_effect=paroles.append), \
                patch.object(hermes, "_appeler_hermes", side_effect=retour if isinstance(retour, Exception) else None,
                             return_value=None if isinstance(retour, Exception) else retour):
            r = hermes.deleguer_en_fond("Fais X", livrable=livrable, **kw)
        return r, fins, paroles

    def test_reponse_vide_n_est_pas_un_succes(self):
        _, fins, paroles = self._deleguer(("(reponse vide d'Hermes)", None, None, ""))
        self.assertEqual(fins[0][0], "echouee")
        self.assertNotIn("termine", " ".join(paroles).lower().replace("pas abouti", ""))

    def test_erreur_hermes_est_annoncee_comme_echec(self):
        _, fins, paroles = self._deleguer(RuntimeError("API cassée"))
        self.assertEqual(fins[0][0], "echouee")
        self.assertIn("echoue", paroles[0])

    def test_livrable_present_et_lisible(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "resultat.md"
            f.write_text("contenu", encoding="utf-8")
            _, fins, paroles = self._deleguer(("Voila.\nRESUME: Fichier cree.", 1, 0.0, "m"), livrable=str(f))
        self.assertEqual(fins[0][0], "terminee")
        self.assertIn("present et lisible", paroles[0])

    def test_livrable_absent_succes_partiel(self):
        _, fins, paroles = self._deleguer(("Voila.\nRESUME: Fichier cree.", 1, 0.0, "m"),
                                          livrable="/chemin/inexistant/resultat.md")
        self.assertEqual(fins[0][0], "partielle")
        self.assertIn("n'existe pas", paroles[0])
        self.assertNotIn("a termine", paroles[0])

    def test_livrable_vide_est_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "vide.md"
            f.write_text("", encoding="utf-8")
            ok, detail = hermes.verifier_livrable(str(f))
        self.assertFalse(ok)
        self.assertIn("vide", detail)

    def test_accuse_de_delegation_est_honnete(self):
        r, _, _ = self._deleguer(("Voila.\nRESUME: ok.", 1, 0.0, "m"))
        self.assertTrue(r.succes)
        self.assertFalse(r.verifie)              # l'annonce de delegation ne vaut pas preuve de resultat
        self.assertIn("tache_id", r.details)

    def test_taches_hermes_montre_les_echecs(self):
        taches = [{"statut": "echouee", "tache": "Analyse le budget", "resume": ""},
                  {"statut": "partielle", "tache": "Ecris le fichier", "resume": ""}]
        with patch.object(hermes, "taches_liste", return_value=taches):
            texte = hermes.taches_hermes()
        self.assertIn("sans succès complet", texte)
        self.assertIn("Analyse le budget", texte)

    def test_aucun_secret_jarvis_dans_le_prompt(self):
        self.assertNotIn("cle", hermes._prompt_hermes("tache").lower().replace("clairement", ""))


# ------------------------------------------------------------------ auto-modification (S9, git REEL)
def _git(d, *a):
    return subprocess.run(["git", *a], cwd=d, capture_output=True, text=True, check=True).stdout.strip()


class TestAutoModification(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        _git(self.d, "init", "-q", "-b", "main")
        _git(self.d, "config", "user.email", "t@example.org")
        _git(self.d, "config", "user.name", "t")
        (self.d / "core").mkdir()
        (self.d / "core" / "module.py").write_text("VALEUR = 1\n", encoding="utf-8")
        (self.d / ".gitignore").write_text("logs/\n", encoding="utf-8")
        _git(self.d, "add", "-A")
        _git(self.d, "commit", "-q", "-m", "init")
        self.base = _git(self.d, "rev-parse", "HEAD")
        self.ok = [[sys.executable, "-c", "pass"]]
        self.ko = [[sys.executable, "-c", "import sys; sys.exit(1)"]]

    def tearDown(self):
        self._tmp.cleanup()

    def test_cycle_complet_commit_seulement_si_tests_verts(self):
        etat = am.demarrer(self.d, "test valeur")
        self.assertTrue(etat["branche"].startswith("jarvis/auto-"))
        self.assertEqual(_git(self.d, "rev-parse", "--abbrev-ref", "HEAD"), etat["branche"])
        am.ecrire_fichier(self.d, "core/module.py", "VALEUR = 2\n")
        self.assertIn("+VALEUR = 2", am.diff(self.d))
        with self.assertRaises(am.ErreurAutoModif):                  # pas de commit sans tests
            am.enregistrer(self.d, "x")
        ok, _ = am.valider(self.d, commandes=self.ok)
        self.assertTrue(ok)
        sha = am.enregistrer(self.d, "valeur 2")
        self.assertNotEqual(sha, self.base)
        am.terminer(self.d)
        self.assertEqual(_git(self.d, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual((self.d / "core" / "module.py").read_text(encoding="utf-8"), "VALEUR = 1\n")  # main intact

    def test_tests_en_echec_interdisent_le_commit(self):
        am.demarrer(self.d, "casse")
        am.ecrire_fichier(self.d, "core/module.py", "VALEUR = (\n")
        ok, _ = am.valider(self.d, commandes=self.ko)
        self.assertFalse(ok)
        with self.assertRaises(am.ErreurAutoModif):
            am.enregistrer(self.d, "casse")

    def test_modification_de_test_puis_restauration(self):
        """Critere S9 : « Modification de test puis restauration reussie »."""
        am.demarrer(self.d, "restauration")
        am.ecrire_fichier(self.d, "core/module.py", "VALEUR = 999\n")
        am.ecrire_fichier(self.d, "core/nouveau.py", "X = 1\n")
        am.annuler(self.d)
        self.assertEqual(_git(self.d, "rev-parse", "HEAD"), self.base)
        self.assertEqual(_git(self.d, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual((self.d / "core" / "module.py").read_text(encoding="utf-8"), "VALEUR = 1\n")
        self.assertFalse((self.d / "core" / "nouveau.py").exists())
        self.assertEqual(_git(self.d, "branch", "--list", "jarvis/*"), "")
        self.assertEqual(_git(self.d, "status", "--porcelain"), "")

    def test_refus_si_modifications_non_enregistrees(self):
        (self.d / "core" / "module.py").write_text("VALEUR = 7\n", encoding="utf-8")
        with self.assertRaises(am.ErreurAutoModif):
            am.demarrer(self.d, "x")
        self.assertEqual((self.d / "core" / "module.py").read_text(encoding="utf-8"), "VALEUR = 7\n")

    def test_fichiers_proteges_et_chemins_hors_projet(self):
        am.demarrer(self.d, "garde-fous")
        for chemin in ("config.yaml", ".env", "core/registre.py", "core/auto_modification.py",
                       ".git/config", "../hors.py", "notes/idees.md", "core/mon_secret.py"):
            with self.subTest(chemin=chemin):
                with self.assertRaises(am.ErreurAutoModif):
                    am.ecrire_fichier(self.d, chemin, "x")
        am.annuler(self.d)

    def test_une_seule_session_a_la_fois(self):
        am.demarrer(self.d, "a")
        with self.assertRaises(am.ErreurAutoModif):
            am.demarrer(self.d, "b")
        am.annuler(self.d)

    def test_redemarrage_supervise(self):
        ok, _ = am.redemarrage_supervise([sys.executable, "-c", "import time; time.sleep(30)"], delai=1.0)
        self.assertTrue(ok)
        ok, detail = am.redemarrage_supervise([sys.executable, "-c", "raise SystemExit(3)"], delai=2.0)
        self.assertFalse(ok)
        self.assertIn("code 3", detail)
        ok, detail = am.redemarrage_supervise([sys.executable, "-c", "import time; time.sleep(30)"],
                                              delai=0.5, sante=lambda: False)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
