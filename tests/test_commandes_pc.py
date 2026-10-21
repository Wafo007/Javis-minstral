"""Commandes PC deterministes (sans LLM) : clic, souris, clavier, fenetres, recherche, enchainement."""
from __future__ import annotations

import ctypes
import types
import unittest
from unittest.mock import MagicMock, patch

if not hasattr(ctypes, "windll"):                      # tests lances hors Windows
    ctypes.windll = MagicMock()

from core import registre
from tools import apps
from tools import controle_pc as pc


class TestRouteurSimple(unittest.TestCase):
    CAS = {
        "clique": ("souris_clic", {"bouton": "gauche"}),
        "clique ici": ("souris_clic", {"bouton": "gauche"}),
        "double clic": ("souris_clic", {"bouton": "gauche", "double": True}),
        "clic droit": ("souris_clic", {"bouton": "droite"}),
        "descends la page": ("souris_defiler", {"sens": "bas", "crans": 5}),
        "remonte un peu": ("souris_defiler", {"sens": "haut", "crans": 2}),
        "déplace la souris vers la droite de 300": ("souris_deplacer", {"direction": "droite", "pixels": 300}),
        "centre la souris": ("souris_deplacer", {"direction": "centre"}),
        "appuie sur ctrl s": ("appuyer_touches", {"combinaison": "ctrl+s"}),
        "appuie sur entrée": ("appuyer_touches", {"combinaison": "entree"}),
        "clique sur le bouton Enregistrer": ("cliquer_bouton", {"nom": "Enregistrer"}),
        "appuie sur Lancer": ("cliquer_bouton", {"nom": "Lancer"}),
        "Jarvis, clique sur Paramètres s'il te plaît": ("cliquer_bouton", {"nom": "Paramètres"}),
        "tape Bonjour tout le monde": ("taper_texte", {"texte": "Bonjour tout le monde"}),
        "écris Éléphant rose": ("taper_texte", {"texte": "Éléphant rose"}),
        "passe sur Spotify": ("activer_fenetre", {"titre": "Spotify"}),
        "cherche Daft Punk sur Spotify": ("rechercher_dans_application", {"application": "spotify", "requete": "Daft Punk"}),
        "cherche chat mignon sur YouTube": ("browser_open", {"url": "youtube", "recherche": "chat mignon"}),
        "cherche météo sur google": ("browser_open", {"recherche": "météo"}),
        "ferme la fenêtre": ("appuyer_touches", {"combinaison": "alt+f4"}),
        "nouvel onglet": ("appuyer_touches", {"combinaison": "ctrl+t"}),
        "montre le bureau": ("appuyer_touches", {"combinaison": "win+d"}),
        "tout en bas": ("appuyer_touches", {"combinaison": "ctrl+end"}),
    }

    def test_phrases_reconnues(self):
        for phrase, attendu in self.CAS.items():
            self.assertEqual(pc._route_simple(phrase), attendu, phrase)

    def test_phrases_laissees_au_llm(self):
        for phrase in ("mets le volume à 30", "quelle heure est-il", "écris un mail à Paul", "tape sur la table",
                       "monte le volume", "descends au salon", "ouvre Chrome", "cherche un restaurant"):
            self.assertIsNone(pc._route_simple(phrase), phrase)

    def test_actions_sensibles_jamais_cliquees_a_l_aveugle(self):
        with patch.object(pc, "_fenetre_cible", return_value=(1, "App", "a.exe")), \
                patch.object(pc, "_controles", return_value=[("bouton", "Supprimer le compte", 5, 5)]):
            self.assertIn("sans ta confirmation", pc.cliquer_bouton("Supprimer le compte"))


class TestEnchainement(unittest.TestCase):
    def test_decoupage_seulement_devant_un_verbe(self):
        self.assertEqual(pc._decouper("ouvre Chrome et lance YouTube"), ["ouvre Chrome", "lance YouTube"])
        self.assertEqual(pc._decouper("tape Tom et Jerry"), ["tape Tom et Jerry"])
        self.assertEqual(len(pc._decouper("ouvre le bloc-notes puis tape bonjour puis appuie sur ctrl s")), 3)
        self.assertEqual(pc._decouper("passe sur Spotify, cherche Daft Punk sur Spotify")[1],
                         "cherche Daft Punk sur Spotify")

    def test_chaine_reconnue_integralement(self):
        r = pc.router_commande_pc("ouvre Chrome et lance YouTube")
        self.assertEqual(r[0], "enchainer_commandes")
        self.assertEqual(r[1]["etapes"], ["ouvre Chrome", "lance YouTube"])

    def test_chaine_partiellement_comprise_va_au_llm(self):
        self.assertIsNone(pc.router_commande_pc("ouvre Chrome et mets une musique triste"))
        self.assertIsNone(pc.router_commande_pc("ouvre Chrome et dis-moi la météo"))

    def test_une_seule_commande_n_est_pas_une_chaine(self):
        self.assertEqual(pc.router_commande_pc("tape Tom et Jerry"), ("taper_texte", {"texte": "Tom et Jerry"}))

    def test_execution_dans_l_ordre_et_arret_sur_confirmation(self):
        appels = []
        outils = {"ouvrir_navigateur": types.SimpleNamespace(confirmation=False, nom="ouvrir_navigateur"),
                  "browser_open": types.SimpleNamespace(confirmation=False, nom="browser_open")}
        with patch.object(registre, "get", side_effect=outils.get), \
                patch.object(registre, "executer", side_effect=lambda o, a=None: appels.append((o.nom, a)) or "ok"), \
                patch.object(pc.time, "sleep"):
            txt = pc.enchainer_commandes(["ouvre Chrome", "lance YouTube"])
        self.assertEqual([a[0] for a in appels], ["ouvrir_navigateur", "browser_open"])
        self.assertEqual(txt, "ok ok")
        outils["browser_open"].confirmation = True
        appels.clear()
        with patch.object(registre, "get", side_effect=outils.get), \
                patch.object(registre, "executer", side_effect=lambda o, a=None: appels.append(o.nom) or "ok"), \
                patch.object(pc.time, "sleep"):
            txt = pc.enchainer_commandes(["ouvre Chrome", "lance YouTube"])
        self.assertEqual(appels, ["ouvrir_navigateur"])           # jamais d'outil a confirmation dans une chaine
        self.assertIn("confirmation", txt)


class TestOuverture(unittest.TestCase):
    def test_mon_navigateur_et_navigateurs(self):
        self.assertEqual(apps.router_ouverture_simple("Ouvre mon navigateur.")[0], "browser_open")
        for phrase, nom in (("ouvre Chrome", "chrome"), ("lance Firefox", "firefox"), ("ouvre Edge", "edge")):
            self.assertEqual(apps.router_ouverture_simple(phrase), ("ouvrir_navigateur", {"nom": nom}))

    def test_application_inconnue_cherchee_dans_le_menu_demarrer(self):
        with patch.object(apps, "_apps", return_value={}), \
                patch("tools.controle_pc.lancer_application_pc", return_value="Steam est ouvert.") as l:
            self.assertEqual(apps.launch_app("Steam"), "Steam est ouvert.")
            l.assert_called_once_with("Steam")
        with patch.object(apps, "_apps", return_value={}), \
                patch("tools.controle_pc.lancer_application_pc", return_value="Je ne trouve pas d'application « X »."):
            self.assertIn("Je ne connais pas X", apps.launch_app("X"))

    def test_ouvrir_navigateur_explicite_et_generique(self):
        with patch.object(pc, "_activer", return_value=None), patch.object(pc, "_lancer", return_value="Google Chrome"), \
                patch("tools.navigateur._chrome_exe", return_value=None):
            self.assertEqual(pc.ouvrir_navigateur("chrome"), "Google Chrome est ouvert.")
        with patch("core.ouvrir_web.ouvrir_url", return_value=True) as o:
            self.assertIn("ouvert", pc.ouvrir_navigateur("mon navigateur"))
            o.assert_called_once()


class TestSouris(unittest.TestCase):
    def test_clic_et_molette(self):
        mouse = MagicMock()
        with patch("tools.souris._user32", mouse):
            self.assertEqual(pc.souris_clic("gauche", True), "Double clic.")
            self.assertEqual(mouse.mouse_event.call_count, 4)
            mouse.reset_mock()
            pc.souris_defiler("bas", 3)
            self.assertEqual(mouse.mouse_event.call_count, 3)
            self.assertEqual(mouse.mouse_event.call_args.args[3], (-120) & 0xFFFFFFFF)

    def test_deplacement_relatif(self):
        with patch.object(pc, "_position", return_value=(100, 100)), \
                patch("tools.souris._placer_curseur", return_value=True) as pl:
            pc.souris_deplacer("droite", 50)
            pl.assert_called_once_with(150, 100)


class TestRobustesse(unittest.TestCase):
    def test_elevenlabs_disjoncteur(self):
        from core import tts
        tts._EL_HS["jusqu"] = 0.0
        prov = tts.ElevenLabsProvider.__new__(tts.ElevenLabsProvider)
        prov.cle, prov.voix, prov.modele = "k", "v", "m"
        appels = []

        def echec(*a, **k):
            appels.append(1)
            raise OSError("getaddrinfo failed")
        with patch.object(tts.urllib.request, "urlopen", echec):
            self.assertIsNone(prov.synthetiser("Bonjour"))
            self.assertIsNone(prov.synthetiser("Encore"))      # 2e appel : aucun reseau, repli immediat
        self.assertEqual(len(appels), 1)
        tts._EL_HS["jusqu"] = 0.0

    def test_calibration_plafonnee(self):
        import sys
        sys.modules.setdefault("sounddevice", types.ModuleType("sounddevice"))
        import jarvis14
        with patch.object(jarvis14, "lire_bloc", return_value=[0.0]), \
                patch.object(jarvis14, "niveau", return_value=0.03), patch.object(jarvis14.time, "time", side_effect=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 2.0]):
            self.assertIsNone(jarvis14._calibrer_seuils(None))      # bruit anormal : seuils par defaut
        with patch.object(jarvis14, "lire_bloc", return_value=[0.0]), \
                patch.object(jarvis14, "niveau", return_value=0.015), patch.object(jarvis14.time, "time", side_effect=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 2.0]):
            sil, par = jarvis14._calibrer_seuils(None)
            self.assertLessEqual(sil, 0.02)
            self.assertLessEqual(par, 0.045)

    def test_delai_apres_parole_court(self):
        import sys
        sys.modules.setdefault("sounddevice", types.ModuleType("sounddevice"))
        import jarvis14
        from collections import deque
        dormi = []
        with patch.object(jarvis14.time, "sleep", side_effect=dormi.append), \
                patch.object(jarvis14.config, "reglage", return_value=0.8):     # ancienne valeur de config
            jarvis14._apres_parole(types.SimpleNamespace(read_available=0), deque())
        self.assertLessEqual(dormi[0], 0.4)

    def test_catalogue_non_elargi_pour_ouvre_mon_navigateur(self):
        from core.routage_intentions import modules_pour_phrase
        m = modules_pour_phrase("Ouvre mon navigateur.")
        self.assertNotIn("souris", m)
        self.assertNotIn("ecran", m)
        self.assertNotIn("apps", m)


if __name__ == "__main__":
    unittest.main()
