"""Assistant personnel : salutation, voix naturelle, voix, modes, routines, contexte, erreurs.

Aucun materiel audio ni reseau : tout est teste sur des fonctions pures / fichiers temporaires.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from core import (accueil, commandes_locales, contexte, erreurs, modes_usage, routines,
                  voix_naturelle, voix_profils, wake)
from core.confirmation_vocale import NON, OUI, interpreter_confirmation

pv = voix_naturelle.pour_la_voix


def _conf(valeurs):
    return lambda chemin, defaut=None: valeurs.get(chemin, defaut)


class Isole(unittest.TestCase):
    """Etat sur disque et config isoles pour chaque test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.conf = {}
        self._p = [patch.object(modes_usage, "FICHIER", self.tmp / "mode.json"),
                   patch.object(voix_profils, "FICHIER", self.tmp / "voix.json"),
                   patch.object(modes_usage, "_reglage", lambda c, d=None: self.conf.get(c, d)),
                   patch.object(accueil, "_reglage", lambda c, d=None: self.conf.get(c, d)),
                   patch.object(routines, "_reglage", lambda c, d=None: self.conf.get(c, d)),
                   patch.object(voix_profils, "_reglage", lambda c, d=None: self.conf.get(c, d)),
                   patch.object(voix_profils, "voix_sapi", lambda: []),
                   patch.object(voix_profils, "voix_elevenlabs", lambda: [])]
        for p in self._p:
            p.start()
        accueil._ETAT.update({"derniere": None, "dernier_choix": None})

    def tearDown(self):
        for p in self._p:
            p.stop()


class TestWakeWord(unittest.TestCase):
    def test_variantes_jarvis(self):
        for t in ("Jarvis, quelle heure", "hey Jarvis", "Djarvis", "Hey, Javis"):
            self.assertGreater(wake.score_jarvis(t), 0, t)
        for t in ("bonjour tout le monde", "service", "harvest"):
            self.assertEqual(wake.score_jarvis(t), 0, t)

    def test_pipeline_audio_synthetique(self):
        w = wake.WakeWhisper(transcrire=lambda a: "ok Jarvis" if len(a) > 8000 else "")
        rng = np.random.default_rng(0)
        bloc = lambda amp: (rng.normal(0, amp, 1280) * 32767).astype(np.int16)
        for _ in range(30):
            w.predict(bloc(0.002))
        for _ in range(12):
            w.predict(bloc(0.08))
        meilleur = 0.0
        for _ in range(15):
            meilleur = max(meilleur, w.predict(bloc(0.002))["jarvis"])
            time.sleep(0.05)
        self.assertGreaterEqual(meilleur, 0.6)


class TestSalutation(Isole):
    def test_nom_et_moment(self):
        self.assertIn("Bonjour Wafo Arold", accueil.salutation(dt.datetime(2026, 1, 1, 9), choix=lambda l: l[0]))
        self.assertIn("Bonjour Wafo Arold", accueil.salutation(dt.datetime(2026, 1, 1, 15), choix=lambda l: l[0]))
        self.assertIn("Bonsoir Wafo Arold", accueil.salutation(dt.datetime(2026, 1, 1, 20), choix=lambda l: l[0]))

    def test_nom_majuscules_et_config(self):
        self.conf["assistant.nom_utilisateur"] = "WAFO AROLD"
        self.assertEqual(accueil.nom_utilisateur(), "Wafo Arold")
        self.conf["assistant.nom_utilisateur"] = "Zoe"
        self.assertEqual(accueil.nom_utilisateur(), "Zoe")

    def test_retour_apres_absence(self):
        accueil.noter_interaction(0)
        txt = accueil.salutation(dt.datetime(2026, 1, 1, 9), instant=10 * 3600, choix=lambda l: l[0])
        self.assertEqual(txt, "Ravi de vous revoir, Wafo Arold.")

    def test_modes_et_desactivation(self):
        self.assertNotIn("Bonjour", accueil.salutation(dt.datetime(2026, 1, 1, 9), mode="nuit"))
        self.conf["accueil.actif"] = False
        self.assertIsNone(accueil.salutation())

    def test_variation_sans_repetition(self):
        a = accueil.salutation(dt.datetime(2026, 1, 1, 9))
        b = accueil.salutation(dt.datetime(2026, 1, 1, 9))
        self.assertNotEqual(a, b)


class TestVoixNaturelle(unittest.TestCase):
    def test_exemple_demande(self):
        r = pv("**Voici le résultat :** 😊\n\n*Le téléchargement est terminé.*\n\n### Informations\n\n"
               "* Fichier téléchargé\n* Taille : 250 Mo")
        self.assertEqual(r, "Voici le résultat. Le téléchargement est terminé. Informations. "
                            "Fichier téléchargé. Taille: 250 mégaoctets.")
        for interdit in ("*", "#", "😊", "Mo"):
            self.assertNotIn(interdit, r)

    def test_meteo_unites(self):
        r = pv("**Météo actuelle**\n\n* Température : 24 °C\n* Humidité : 72 %\n* Vent : 12 km/h")
        self.assertIn("24 degrés", r)
        self.assertIn("72 pour cent", r)
        self.assertIn("12 kilomètres par heure", r)

    def test_nombres_sans_deformation(self):
        self.assertIn("3 virgule 14", pv("Pi vaut 3.14"))
        self.assertIn("Wi-Fi", pv("Le Wi-Fi marche"))
        self.assertIn("1.2.3", pv("version 1.2.3"))

    def test_urls_emails_liens(self):
        self.assertIn("email arobase example point com", pv("[email@example.com](mailto:email@example.com)"))
        self.assertNotIn("http", pv("Voir https://exemple.com/a?b=1 maintenant"))
        self.assertEqual(pv("[le site](https://x.com)"), "le site")

    def test_dates_heures(self):
        r = pv("RDV le 05/03/2025 à 14h30, puis 9h")
        self.assertIn("5 mars 2025", r)
        self.assertIn("14 heures 30", r)
        self.assertIn("9 heures", r)

    def test_code_tableau_html_ponctuation(self):
        self.assertIn("affiché à l'écran", pv("```py\nprint(1)\n```"))
        self.assertEqual(pv("| a | b |\n|---|---|\n| 1 | 2 |"), "a, b. 1, 2.")
        self.assertEqual(pv("<b>gras</b> ok !!!"), "gras ok!")
        self.assertEqual(pv("1. Un\n2. Deux"), "Un. Deux.")

    def test_vide_et_texte_simple(self):
        self.assertEqual(pv(""), "")
        self.assertEqual(pv("Chrome est ouvert."), "Chrome est ouvert.")

    def test_affichage_non_degrade(self):
        original = "**Gras** et *italique* 😊"
        pv(original)                       # la fonction ne modifie jamais l'original
        self.assertEqual(original, "**Gras** et *italique* 😊")


class TestVoix(Isole):
    P = {"jarvis": {"nom": "jarvis", "moteur": "elevenlabs", "genre": "m", "langue": "fr", "voix": "X"},
         "Hortense": {"nom": "Hortense", "moteur": "windows", "genre": "f", "langue": "fr"},
         "Zira": {"nom": "Zira", "moteur": "windows", "genre": "f", "langue": "en"}}

    def test_resolution(self):
        r = lambda c: voix_profils.resoudre(c, self.P)
        self.assertEqual(r("la voix féminine"), "Hortense")
        self.assertEqual(r("masculine"), "jarvis")
        self.assertEqual(r("voix anglaise"), "Zira")
        self.assertEqual(r("Zira"), "Zira")
        self.assertIsNone(r("voix inexistante"))

    def test_changement_et_retour(self):
        self.conf["tts.profils"] = {k: {kk: vv for kk, vv in v.items() if kk != "nom"} for k, v in self.P.items()}
        with patch.object(voix_profils, "appliquer", return_value=True):
            self.assertEqual(voix_profils.utiliser("féminine"), "Voix Hortense activée.")
            self.assertEqual(voix_profils.utiliser("masculine"), "Voix jarvis activée.")
            self.assertEqual(voix_profils.precedente(), "Retour à la voix Hortense.")

    def test_voix_inexistante_et_liste(self):
        self.conf["tts.profils"] = {"douce": {"moteur": "windows", "genre": "f", "langue": "fr"}}
        self.assertIn("douce (féminine, française)", voix_profils.liste_texte())
        self.assertIn("Je n'ai pas de voix", voix_profils.utiliser("klingon"))

    def test_aucun_profil_pas_de_faux_id(self):
        self.assertIn("Aucune voix configurée", voix_profils.liste_texte())


class TestModes(Isole):
    def test_nuit_manuel_persistant(self):
        self.assertEqual(modes_usage.definir_mode("nuit"), "Mode nuit activé.")
        self.assertEqual(modes_usage.mode_effectif(), "nuit")
        p = modes_usage.parametres()
        self.assertLess(p["volume"], 1.0)
        self.assertLess(p["vitesse"], 1.0)
        self.assertEqual(modes_usage.desactiver_mode("nuit"), "Mode nuit désactivé.")
        self.assertEqual(modes_usage.mode_effectif(), "normal")

    def test_nuit_automatique_et_forcage(self):
        self.conf.update({"mode_nuit.auto": True, "mode_nuit.heure_debut": "23:00", "mode_nuit.heure_fin": "07:00"})
        self.assertEqual(modes_usage.mode_effectif(dt.datetime(2026, 1, 1, 23, 30)), "nuit")
        self.assertEqual(modes_usage.mode_effectif(dt.datetime(2026, 1, 2, 3, 0)), "nuit")
        self.assertEqual(modes_usage.mode_effectif(dt.datetime(2026, 1, 2, 12, 0)), "normal")
        nuit = dt.datetime(2026, 1, 2, 2, 0)
        modes_usage.desactiver_mode("nuit", now=nuit)           # forcer la sortie pendant la plage
        self.assertEqual(modes_usage.mode_effectif(nuit), "normal")
        self.assertEqual(modes_usage.mode_effectif(dt.datetime(2026, 1, 2, 23, 30)), "nuit")

    def test_configuration_volume_nuit(self):
        self.conf["mode_nuit.volume"] = 0.3
        modes_usage.definir_mode("nuit")
        self.assertEqual(modes_usage.parametres()["volume"], 0.3)

    def test_changement_de_modes_et_aliases(self):
        for phrase, attendu in (("travail", "travail"), ("gaming", "gaming"), ("ne pas déranger", "ne_pas_deranger"),
                                ("mode jeu", "gaming"), ("normal", "normal")):
            self.assertEqual(modes_usage.normaliser_mode(phrase), attendu)
        modes_usage.definir_mode("travail")
        self.assertEqual(modes_usage.parametres()["longueur"], "courte")
        self.assertIn("Je ne connais pas", modes_usage.definir_mode("zorglub"))

    def test_proactivite(self):
        self.assertTrue(modes_usage.proactif_autorise("info"))
        modes_usage.definir_mode("ne_pas_deranger")
        self.assertFalse(modes_usage.proactif_autorise("important"))
        self.assertTrue(modes_usage.proactif_autorise("critique"))     # minuteurs/alarmes passent toujours
        modes_usage.definir_mode("nuit")
        self.assertFalse(modes_usage.proactif_autorise("info"))
        self.assertTrue(modes_usage.proactif_autorise("important"))
        modes_usage.definir_proactif(False)
        self.assertFalse(modes_usage.proactif_autorise("important"))

    def test_callback_et_consigne(self):
        vus = []
        modes_usage.definir_rappel(lambda m, p: vus.append(m))
        modes_usage.definir_mode("nuit")
        self.assertEqual(vus, ["nuit"])
        self.assertIn("quelques mots", modes_usage.consigne_systeme())
        modes_usage.definir_rappel(None)


class TestCommandesLocales(Isole):
    def setUp(self):
        super().setUp()
        self.conf["tts.profils"] = {"douce": {"moteur": "windows", "genre": "f", "langue": "fr"}}

    def test_modes_a_la_voix(self):
        e = commandes_locales.essayer
        self.assertEqual(e("Jarvis, active le mode nuit."), "Mode nuit activé.")
        self.assertEqual(e("désactive le mode nuit"), "Mode nuit désactivé.")
        self.assertEqual(e("active le mode travail"), "Mode travail activé.")
        self.assertEqual(e("passe en mode gaming"), "Mode gaming activé.")
        self.assertEqual(e("active le mode ne pas déranger"), "Mode ne pas déranger activé.")
        self.assertEqual(e("retour au mode normal"), "Mode normal activé.")

    def test_voix_a_la_voix(self):
        self.assertIn("douce", commandes_locales.essayer("Quelles voix sont disponibles ?"))
        with patch.object(voix_profils, "appliquer", return_value=True):
            self.assertEqual(commandes_locales.essayer("Utilise la voix féminine."), "Voix douce activée.")
        self.assertIn("Je n'ai pas de voix", commandes_locales.essayer("utilise la voix zzz"))

    def test_phrases_normales_vont_au_llm(self):
        for ph in ("quelle heure est-il", "ouvre Chrome", "mets de la musique", "Quel temps demain ?"):
            self.assertIsNone(commandes_locales.essayer(ph), ph)

    def test_commande_combinee_non_interceptee(self):
        self.assertIsNone(commandes_locales.essayer("ouvre Chrome, lance YouTube et mets le volume à 30 %"))

    def test_routine(self):
        appels = []
        outil_ok = SimpleNamespace(confirmation=False)
        outil_n3 = SimpleNamespace(confirmation=True)
        reg = SimpleNamespace(get=lambda n: {"a": outil_ok, "b": outil_n3}.get(n),
                              executer=lambda o, args=None: appels.append(args))
        self.conf["routines"] = {"jour": {"phrases": ["commence ma journée"], "mode": "travail",
                                          "actions": [{"outil": "a", "args": {"x": 1}}, {"outil": "b"},
                                                      {"outil": "inconnu"}], "dire": "Allons-y {nom}."}}
        nom, d = routines.trouver("Jarvis commence ma journée")
        txt = routines.executer(nom, d, registre=reg, modes=modes_usage, nom_utilisateur="Wafo Arold")
        self.assertEqual(appels, [{"x": 1}])                       # l'outil a confirmation n'est jamais lance
        self.assertIn("Allons-y Wafo Arold.", txt)
        self.assertIn("2 actions n'ont pas abouti", txt)
        self.assertEqual(modes_usage.mode_effectif(), "travail")


class TestContexteEtErreurs(unittest.TestCase):
    def setUp(self):
        contexte.oublier()

    def test_contexte_recent_et_expiration(self):
        contexte.noter_action("ouvrir_application", {"nom": "Chrome"}, instant=1000)
        self.assertIn("ouvrir_application(nom=Chrome)", contexte.consigne(instant=1100))
        self.assertNotIn("ouvrir_application", contexte.consigne(instant=1000 + 3600))

    def test_correction_dans_la_consigne(self):
        c = contexte.consigne()
        self.assertIn("non, Firefox", c)
        self.assertIn("plusieurs actions", c)

    def test_pas_de_stockage_disque_et_max_3(self):
        for i in range(6):
            contexte.noter_action("o", {"i": i})
        self.assertEqual(len(contexte.recentes()), 3)

    def test_erreurs_humaines(self):
        self.assertEqual(erreurs.message_humain(FileNotFoundError("x")), "Je n'ai pas trouvé ce fichier.")
        self.assertIn("autorisation", erreurs.message_humain(PermissionError()))
        self.assertIn("temporairement indisponible", erreurs.message_humain(ConnectionError()))
        self.assertEqual(erreurs.message_humain(ValueError("boom"), "ouvrir_application"),
                         "Je n'ai pas réussi à ouvrir cette application.")
        for exc in (RuntimeError("Traceback"), KeyError("k")):
            m = erreurs.message_humain(exc)
            self.assertNotIn("Traceback", m)
            self.assertNotIn("Exception", m)


class TestConfirmations(unittest.TestCase):
    def test_oui_non_annule(self):
        self.assertEqual(interpreter_confirmation("Oui."), OUI)
        self.assertEqual(interpreter_confirmation("Non."), NON)
        self.assertEqual(interpreter_confirmation("Annule."), NON)
        self.assertEqual(interpreter_confirmation("oui mais non"), NON)


if __name__ == "__main__":
    unittest.main()
