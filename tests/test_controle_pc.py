"""Controle du PC : raccourcis, fenetres, boutons par nom, routage des outils, vision Mistral."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import cloud
from core.routage_intentions import modules_pour_phrase
from tools import controle_pc as pc
from tools import navigateur


class TestClavier(unittest.TestCase):
    def test_combinaisons(self):
        self.assertEqual(pc.analyser_combinaison("ctrl+l"), [0x11, ord("L")])
        self.assertEqual(pc.analyser_combinaison("Ctrl + Shift + T"), [0x11, 0x10, ord("T")])
        self.assertEqual(pc.analyser_combinaison("entrée"), [0x0D])
        self.assertEqual(pc.analyser_combinaison("f5"), [0x74])
        self.assertEqual(pc.analyser_combinaison("alt+tab"), [0x12, 0x09])
        with self.assertRaises(ValueError):
            pc.analyser_combinaison("ctrl+zorglub")
        with self.assertRaises(ValueError):
            pc.analyser_combinaison("")

    def test_ctrl_alt_suppr_refuse(self):
        with patch.object(pc, "_appuyer") as p:
            self.assertIn("n'appuie pas", pc.appuyer_touches("ctrl+alt+suppr"))
            p.assert_not_called()
            pc.appuyer_touches("ctrl+l")
            p.assert_called_once()


class TestSelection(unittest.TestCase):
    F = [(1, "Daft Punk - Get Lucky", "spotify.exe"), (2, "Document1 - Word", "winword.exe"),
         (3, "Sans titre - Bloc-notes", "notepad.exe")]

    def test_fenetre_par_programme_meme_si_titre_change(self):
        self.assertEqual(pc.choisir_fenetre(self.F, "Spotify")[0], 1)       # titre = morceau en cours
        self.assertEqual(pc.choisir_fenetre(self.F, "word")[0], 2)
        self.assertEqual(pc.choisir_fenetre(self.F, "bloc-notes")[0], 3)
        self.assertIsNone(pc.choisir_fenetre(self.F, "photoshop"))

    def test_application_du_menu_demarrer(self):
        apps = [{"Name": "Spotify", "AppID": "A"}, {"Name": "Spotify Installer", "AppID": "B"},
                {"Name": "Paramètres", "AppID": "C"}]
        self.assertEqual(pc.choisir_app(apps, "spotify")["AppID"], "A")
        self.assertEqual(pc.choisir_app(apps, "parametres")["AppID"], "C")
        self.assertIsNone(pc.choisir_app(apps, "photoshop"))

    def test_bouton_par_nom_sans_accents(self):
        ctl = [("bouton", "Enregistrer sous", 10, 10), ("bouton", "Enregistrer", 20, 20),
               ("bouton", "Paramètres", 30, 30)]
        self.assertEqual(pc.choisir_controle(ctl, "enregistrer")[2], 20)       # exact avant partiel
        self.assertEqual(pc.choisir_controle(ctl, "parametres")[2], 30)
        self.assertIsNone(pc.choisir_controle(ctl, "quitter"))

    def test_cliquer_bouton_introuvable(self):
        with patch.object(pc, "_fenetre_cible", return_value=(9, "App", "app.exe")), \
                patch.object(pc, "_controles", return_value=[("bouton", "OK", 1, 1)]):
            self.assertIn("Je ne vois pas de bouton", pc.cliquer_bouton("Annuler"))

    def test_recherche_dans_application(self):
        etapes = []
        with patch.object(pc, "_activer", return_value=(1, "Spotify", "spotify.exe")), \
                patch.object(pc, "_appuyer", side_effect=lambda c: etapes.append(("touches", c))), \
                patch.object(pc, "_ecrire", side_effect=lambda t: etapes.append(("texte", t))), \
                patch.object(pc.time, "sleep"):
            msg = pc.rechercher_dans_application("Spotify", "Daft Punk")
        self.assertIn("recherche", msg)
        self.assertEqual(etapes[0], ("touches", [0x11, ord("L")]))             # Ctrl+L = barre de recherche
        self.assertIn(("texte", "Daft Punk"), etapes)
        self.assertEqual(etapes[-1], ("touches", [0x0D]))                       # Entree

    def test_application_introuvable(self):
        with patch.object(pc, "_activer", return_value=None), patch.object(pc, "_lancer", return_value=None):
            self.assertIn("Je ne trouve pas", pc.lancer_application_pc("Photoshop"))


class TestRoutageOutils(unittest.TestCase):
    def test_spotify_offre_aussi_le_controle_du_pc(self):
        m = modules_pour_phrase("cherche Daft Punk sur Spotify")
        self.assertTrue({"controle_pc", "spotify"} <= m)

    def test_clic_et_saisie_offrent_les_outils_pc(self):
        for ph in ("clique sur le bouton Enregistrer", "tape bonjour dans le bloc-notes",
                   "appuie sur ctrl+s", "ouvre Discord", "prends le contrôle de mon pc"):
            m = modules_pour_phrase(ph)
            self.assertTrue(m is None or "controle_pc" in m, ph)

    def test_phrase_banale_reste_sans_outil(self):
        self.assertEqual(modules_pour_phrase("merci beaucoup"), set())


class TestNavigateur(unittest.TestCase):
    def test_recherche_sur_site_connu(self):
        self.assertEqual(navigateur._resoudre_cible("youtube", "daft punk"),
                         "https://www.youtube.com/results?search_query=daft+punk")
        self.assertEqual(navigateur._resoudre_cible("spotify", "daft punk"),
                         "https://open.spotify.com/search/daft+punk")
        self.assertIn("google.com/search", navigateur._resoudre_cible("", "godox tl60"))

    @patch("core.ouvrir_web.navigateur_prefere", return_value="chrome")
    def test_message_chrome_precis(self, _):
        with patch.object(navigateur, "_chrome_exe", return_value=None):
            self.assertIn("Je ne trouve pas Google Chrome", navigateur._absent())
        with patch.object(navigateur, "_chrome_exe", return_value="chrome.exe"):
            navigateur._ERREUR[0] = "ModuleNotFoundError: playwright"
            self.assertIn("Playwright", navigateur._absent())
            navigateur._ERREUR[0] = "TimeoutError: x"
            self.assertIn("TimeoutError", navigateur._absent())
        navigateur._ERREUR[0] = ""


class TestFirefoxPilotage(unittest.TestCase):
    @patch("core.ouvrir_web.navigateur_prefere", return_value="firefox")
    def test_firefox_pilote_via_chrome_par_defaut(self, _):
        lance = []
        with patch.object(navigateur, "_BROWSER", None), patch.object(navigateur, "_tenter_cdp", side_effect=[None, "B"]), \
                patch.object(navigateur, "_lancer_chrome", side_effect=lambda p: lance.append(p) or True), \
                patch.object(navigateur, "_port_ouvert", return_value=True), patch.object(navigateur.time, "sleep"):
            self.assertEqual(navigateur._connexion(), "B")
        self.assertEqual(lance, [9222])

    @patch("core.ouvrir_web.navigateur_prefere", return_value="firefox")
    def test_ancien_comportement_si_desactive(self, _):
        with patch.object(navigateur, "reglage", side_effect=lambda c, d=None: False if c == "navigateur.piloter_avec_chrome" else d), \
                patch.object(navigateur, "_BROWSER", None), patch.object(navigateur, "_tenter_cdp", return_value=None), \
                patch.object(navigateur, "_lancer_chrome") as l:
            self.assertIsNone(navigateur._connexion())
            l.assert_not_called()
            self.assertIn("Firefox", navigateur._absent())


class TestVisionMistral(unittest.TestCase):
    def test_modele_de_vision(self):
        self.assertEqual(cloud.modele_vision_mistral("ministral-8b-latest"), "pixtral-12b-latest")
        self.assertEqual(cloud.modele_vision_mistral("open-mistral-nemo"), "pixtral-12b-latest")
        self.assertEqual(cloud.modele_vision_mistral("mistral-small-latest"), "mistral-small-latest")

    def test_action_vision_secours_sur_429(self):
        class E(Exception):
            status_code = 429
        modeles = []

        def create(**k):
            modeles.append(k["model"])
            if k["model"].startswith("pixtral"):
                raise E()
            call = SimpleNamespace(function=SimpleNamespace(arguments='{"action": "fini"}'))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))], usage=None)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(cloud, "fournisseur", return_value="mistral"), \
                patch.object(cloud, "client_mistral", return_value=client), \
                patch.object(cloud, "enregistrer_usage"):
            r = cloud.decider_action_vision("s", "t", "AAAA", {}, nom_modele="ministral-8b-latest")
        self.assertEqual(r, {"action": "fini"})
        self.assertEqual(modeles, ["pixtral-12b-latest", "mistral-small-latest"])


if __name__ == "__main__":
    unittest.main()
