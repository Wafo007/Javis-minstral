"""Non-regression S1/S2/S5/S6/S8 : controle du PC, routage vocal et enchainement.

TOUS ces tests utilisent des doubles (aucune API Windows reelle) : ils prouvent la LOGIQUE de
Jarvis (choix de fenetre, verification du focus, honnetete des messages, routage), PAS le
comportement reel de Windows. La validation reelle est dans scripts/valider_windows.py.
"""
from __future__ import annotations

import ctypes
import types
import unittest
from unittest.mock import MagicMock, patch

from core import registre
from core.resultat import ResultatOutil, est_echec
from core.routage_intentions import decider_prioritaire, modules_pour_phrase
from tools import controle_pc as pc

def setUpModule():
    registre.charger_outils()           # le registre est rempli a la demande (decouverte de tools/)


FENETRES = [
    (101, "Jarvis - powershell", "windowsterminal.exe"),
    (102, "Sans titre – Bloc-notes", "notepad.exe"),
    (103, "controle_pc.py - Visual Studio Code", "code.exe"),
    (104, "Google - Google Chrome", "chrome.exe"),
    (105, "Documents", "explorer.exe"),
]


class TestTrouverFenetre(unittest.TestCase):
    def test_bloc_notes_sous_toutes_les_graphies(self):
        for requete in ("bloc-notes", "Bloc-notes", "bloc notes", "notepad", "Bloc notes"):
            self.assertEqual(pc._trouver_fenetre(requete, FENETRES)[0], 102, requete)

    def test_vscode_chrome_explorateur(self):
        self.assertEqual(pc._trouver_fenetre("VS Code", FENETRES)[0], 103)
        self.assertEqual(pc._trouver_fenetre("visual studio code", FENETRES)[0], 103)
        self.assertEqual(pc._trouver_fenetre("chrome", FENETRES)[0], 104)
        self.assertEqual(pc._trouver_fenetre("explorateur", FENETRES)[0], 105)

    def test_terminal_exclu_des_recherches_approximatives(self):
        # « jarvis » est dans le titre du terminal : il ne doit pas etre active par erreur.
        self.assertIsNone(pc._trouver_fenetre("jarvis", FENETRES))
        self.assertEqual(pc._trouver_fenetre("terminal", FENETRES)[0], 101)

    def test_introuvable(self):
        self.assertIsNone(pc._trouver_fenetre("photoshop", FENETRES))
        self.assertIsNone(pc._trouver_fenetre("", FENETRES))


class TestActivation(unittest.TestCase):
    def test_focus_refuse_n_est_pas_un_succes(self):
        with patch.object(pc, "_trouver_fenetre", return_value=FENETRES[1]), \
                patch.object(pc, "_mettre_au_premier_plan", return_value=False):
            self.assertEqual(pc._activer("bloc-notes")[0], 102)
            self.assertIs(pc._ETAT["focus"], False)
            r = pc.activer_fenetre("bloc-notes")
        self.assertFalse(r.succes)
        self.assertEqual(r.erreur, "focus")
        self.assertNotIn("au premier plan.", str(r).replace("pas pu la mettre au premier plan", ""))

    def test_focus_confirme_est_un_succes_verifie(self):
        with patch.object(pc, "_trouver_fenetre", return_value=FENETRES[1]), \
                patch.object(pc, "_mettre_au_premier_plan", return_value=True):
            r = pc.activer_fenetre("bloc-notes")
        self.assertTrue(r.succes and r.verifie)
        self.assertEqual(r.details["hwnd"], 102)

    def test_fenetre_absente(self):
        with patch.object(pc, "_trouver_fenetre", return_value=None):
            r = pc.activer_fenetre("photoshop")
        self.assertFalse(r.succes)
        self.assertEqual(r.erreur, "introuvable")

    def test_premier_plan_reverifie_avec_getforegroundwindow(self):
        """_mettre_au_premier_plan ne se contente pas de SetForegroundWindow : il relit le premier plan."""
        u = MagicMock()
        u.IsIconic.return_value = 1
        u.GetForegroundWindow.side_effect = [900, 900, 900, 900, 900, 900, 900, 900]
        u.GetWindowThreadProcessId.return_value = 7
        u.AttachThreadInput.return_value = 1
        u.GetAncestor.side_effect = lambda h, _: h
        k = MagicMock()
        k.GetCurrentThreadId.return_value = 1
        fake = types.SimpleNamespace(user32=u, kernel32=k)
        with patch.object(ctypes, "windll", fake, create=True), patch.object(pc, "EST_WINDOWS", True), \
                patch.object(pc.time, "sleep"):
            self.assertFalse(pc._mettre_au_premier_plan(102))       # le premier plan reste 900
        u.ShowWindow.assert_called_with(102, 9)                       # restauration d'une fenetre minimisee
        self.assertEqual(u.SetForegroundWindow.call_count, 3)         # 3 essais
        u.AttachThreadInput.assert_any_call(1, 7, False)              # le rattachement est toujours defait

    def test_premier_plan_reussi(self):
        u = MagicMock()
        u.IsIconic.return_value = 0
        u.GetForegroundWindow.return_value = 102
        u.GetWindowThreadProcessId.return_value = 7
        fake = types.SimpleNamespace(user32=u, kernel32=MagicMock())
        with patch.object(ctypes, "windll", fake, create=True), patch.object(pc, "EST_WINDOWS", True), \
                patch.object(pc.time, "sleep"):
            self.assertTrue(pc._mettre_au_premier_plan(102))


class TestLancement(unittest.TestCase):
    def _fen(self, focus):
        def activer(_):
            pc._ETAT["focus"] = focus
            return FENETRES[1]
        return activer

    def test_deja_ouvert_et_au_premier_plan(self):
        with patch.object(pc, "_activer", side_effect=self._fen(True)):
            r = pc.lancer_application_pc("bloc-notes")
        self.assertTrue(r.succes and r.verifie)
        self.assertIn("au premier plan", r)

    def test_lance_puis_fenetre_constatee(self):
        appels = iter([None, FENETRES[1]])

        def activer(_):
            f = next(appels)
            pc._ETAT["focus"] = True if f else None
            return f
        with patch.object(pc, "_activer", side_effect=activer), \
                patch.object(pc, "_lancer", return_value="Bloc-notes") as lancer, \
                patch.object(pc.time, "sleep"):
            r = pc.lancer_application_pc("bloc-notes")
        lancer.assert_called_once_with("bloc-notes")
        self.assertTrue(r.succes and r.verifie)
        self.assertEqual(str(r), "Bloc-notes est ouvert.")

    def test_lance_mais_aucune_fenetre_n_est_un_echec_dit_comme_tel(self):
        with patch.object(pc, "_activer", return_value=None), \
                patch.object(pc, "_lancer", return_value="Bloc-notes"), \
                patch.object(pc, "_attendre_fenetre", return_value=None):
            r = pc.lancer_application_pc("bloc-notes")
        self.assertFalse(r.succes)
        self.assertEqual(r.erreur, "fenetre_absente")
        self.assertNotIn("est ouvert", r)       # plus de faux « X est ouvert »

    def test_fenetre_ouverte_mais_focus_refuse(self):
        with patch.object(pc, "_activer", side_effect=self._fen(False)):
            r = pc.lancer_application_pc("bloc-notes")
        self.assertFalse(r.succes)
        self.assertEqual(r.erreur, "focus")

    def test_introuvable(self):
        with patch.object(pc, "_activer", return_value=None), patch.object(pc, "_lancer", return_value=None):
            r = pc.lancer_application_pc("Photoshop")
        self.assertFalse(r.succes)
        self.assertTrue(str(r).startswith("Je ne trouve pas"))

    def test_verifier_ouverture_hors_windows_ne_leve_pas(self):
        with patch.object(pc, "_attendre_fenetre", side_effect=OSError("pas windows")):
            r = pc.verifier_ouverture("calculatrice")
        self.assertTrue(r.succes)
        self.assertFalse(r.verifie)             # on ne pretend pas avoir verifie


class TestMenuDemarrer(unittest.TestCase):
    def setUp(self):
        pc._APPS.update(liste=None, echec=0.0)

    def test_liste_vide_n_est_pas_memorisee(self):
        vide = MagicMock(stdout=b"[]", returncode=0)
        plein = MagicMock(stdout='[{"Name":"Bloc-notes","AppID":"A!B"}]'.encode(), returncode=0)
        with patch.object(pc.subprocess, "run", side_effect=[vide, plein]) as run:
            self.assertEqual(pc._apps_demarrer(), [])
            pc._APPS["echec"] = 0.0                    # fin du delai de 60 s
            self.assertEqual(pc._apps_demarrer()[0]["Name"], "Bloc-notes")
        self.assertEqual(run.call_count, 2)

    def test_echec_recent_evite_de_marteler_powershell(self):
        with patch.object(pc.subprocess, "run", side_effect=OSError("bloque")) as run:
            self.assertEqual(pc._apps_demarrer(), [])
            self.assertEqual(pc._apps_demarrer(), [])
        self.assertEqual(run.call_count, 1)

    def test_choisir_app_tiret_et_espace(self):
        apps = [{"Name": "Bloc-notes", "AppID": "N"}, {"Name": "Calculatrice", "AppID": "C"}]
        self.assertEqual(pc.choisir_app(apps, "bloc notes")["AppID"], "N")

    def test_secours_executable_integre_sans_powershell(self):
        with patch.object(pc, "_apps_demarrer") as ps, patch.object(pc.subprocess, "Popen") as popen:
            self.assertEqual(pc._lancer("bloc-notes"), "bloc-notes")
        ps.assert_not_called()
        popen.assert_called_once_with(["notepad.exe"])

    def test_secours_ne_lance_jamais_un_nom_arbitraire(self):
        with patch.object(pc, "_chemin_app_paths", return_value=None), \
                patch.object(pc.shutil, "which", return_value=None), \
                patch.object(pc.subprocess, "Popen") as popen:
            self.assertIsNone(pc._lancer_connu("x & calc"))
        popen.assert_not_called()
        self.assertIsNone(pc._chemin_app_paths("..\\evil.exe"))


class FauxClavier:
    def __init__(self, retour=1):
        self.envoyes, self.retour = [], retour

    def SendInput(self, n, ptr, taille):
        self.envoyes.append(ptr._obj.u.ki.wScan)
        return self.retour


class TestSaisie(unittest.TestCase):
    def _windll(self, clavier):
        return types.SimpleNamespace(user32=clavier, kernel32=MagicMock())

    def test_ecrire_envoie_chaque_unite_utf16(self):
        clavier = FauxClavier()
        with patch.object(ctypes, "windll", self._windll(clavier), create=True), \
                patch.object(pc, "EST_WINDOWS", True), patch.object(pc.time, "sleep"):
            pc._ecrire("é, 😀")
        # é , espace + emoji (2 unites UTF-16) ; chaque unite = 1 appui + 1 relachement
        attendu_unites = [ord("é"), ord(","), ord(" ")] + pc._unites_utf16("😀")
        self.assertEqual(clavier.envoyes, [u for u in attendu_unites for _ in (0, 1)])
        self.assertEqual(len(pc._unites_utf16("😀")), 2)

    def test_sendinput_refuse_leve_une_erreur(self):
        with patch.object(ctypes, "windll", self._windll(FauxClavier(retour=0)), create=True), \
                patch.object(pc, "EST_WINDOWS", True), patch.object(pc.time, "sleep"):
            with self.assertRaises(OSError):
                pc._ecrire("a")

    def test_taper_texte_dans_la_fenetre_cible_avec_verification(self):
        tape = []
        with patch.object(pc, "_activer", side_effect=lambda _: (pc._ETAT.update(focus=True) or FENETRES[1])), \
                patch.object(pc, "_ecrire", side_effect=tape.append), \
                patch.object(pc, "_relire_texte", return_value="Bonjour, je suis Jarvis, assistant intelligent."), \
                patch.object(pc.time, "sleep"):
            r = pc.taper_texte("Bonjour, je suis Jarvis, assistant intelligent.", fenetre="bloc-notes")
        self.assertEqual(tape, ["Bonjour, je suis Jarvis, assistant intelligent."])   # texte EXACT
        self.assertTrue(r.succes and r.verifie)

    def test_pas_de_saisie_si_focus_refuse(self):
        with patch.object(pc, "_activer", side_effect=lambda _: (pc._ETAT.update(focus=False) or FENETRES[1])), \
                patch.object(pc, "_ecrire") as ecrire:
            r = pc.taper_texte("Bonjour", fenetre="bloc-notes")
        ecrire.assert_not_called()
        self.assertFalse(r.succes)
        self.assertEqual(r.erreur, "focus")

    def test_pas_de_saisie_si_fenetre_introuvable(self):
        with patch.object(pc, "_activer", return_value=None), patch.object(pc, "_ecrire") as ecrire:
            r = pc.taper_texte("Bonjour", fenetre="bloc-notes")
        ecrire.assert_not_called()
        self.assertEqual(r.erreur, "introuvable")

    def test_texte_absent_a_la_relecture_est_un_echec(self):
        with patch.object(pc, "_activer", side_effect=lambda _: (pc._ETAT.update(focus=True) or FENETRES[1])), \
                patch.object(pc, "_ecrire"), patch.object(pc, "_relire_texte", return_value="autre chose"), \
                patch.object(pc.time, "sleep"):
            r = pc.taper_texte("Bonjour", fenetre="bloc-notes")
        self.assertFalse(r.succes)
        self.assertEqual(r.erreur, "verification")

    def test_relecture_impossible_est_dite_non_verifiee(self):
        with patch.object(pc, "_activer", side_effect=lambda _: (pc._ETAT.update(focus=True) or FENETRES[1])), \
                patch.object(pc, "_ecrire"), patch.object(pc, "_relire_texte", return_value=None), \
                patch.object(pc.time, "sleep"):
            r = pc.taper_texte("Bonjour", fenetre="bloc-notes")
        self.assertTrue(r.succes)
        self.assertFalse(r.verifie)
        self.assertIn("pas pu vérifier", r)

    def test_refus_de_taper_dans_un_terminal(self):
        with patch.object(pc, "_fenetre_cible", return_value=FENETRES[0]), patch.object(pc, "_ecrire") as ecrire:
            r = pc.taper_texte("rm -rf /")
        ecrire.assert_not_called()
        self.assertEqual(r.erreur, "terminal")

    def test_echec_de_saisie_remonte(self):
        with patch.object(pc, "_fenetre_cible", return_value=FENETRES[1]), \
                patch.object(pc, "_ecrire", side_effect=OSError("uipi")):
            r = pc.taper_texte("Bonjour")
        self.assertFalse(r.succes)
        self.assertEqual(r.erreur, "saisie")

    def test_comparaison_insensible_aux_espaces_et_retours_ligne(self):
        self.assertTrue(pc._texte_retrouve("a\nb  c", "xx a b c yy"))
        self.assertFalse(pc._texte_retrouve("a b", "a c"))


class TestRoutageBlocNotes(unittest.TestCase):
    PHRASE = "Jarvis, ouvre le Bloc-notes et écris : Bonjour, je suis Jarvis, assistant intelligent."

    def test_dictee_conserve_ponctuation_accents_et_casse(self):
        self.assertEqual(pc._texte_dicte("écris : Bonjour, je suis Jarvis, assistant intelligent."),
                         "Bonjour, je suis Jarvis, assistant intelligent.")
        self.assertEqual(pc._texte_dicte("Tape « Éléphant rose ! » s'il te plaît"), "Éléphant rose !")
        self.assertEqual(pc._route_simple("écris Éléphant rose"), ("taper_texte", {"texte": "Éléphant rose"}))

    def test_phrase_cible_est_une_chaine_de_deux_etapes(self):
        r = pc.router_commande_pc(self.PHRASE)
        self.assertEqual(r[0], "enchainer_commandes")
        self.assertEqual(r[1]["etapes"][0], "ouvre le Bloc-notes")
        self.assertEqual(r[1]["etapes"][1], "écris : Bonjour, je suis Jarvis, assistant intelligent.")

    def test_decision_commune_choisit_ouvrir_puis_taper_texte_jamais_noter(self):
        d = decider_prioritaire(self.PHRASE)
        self.assertEqual((d.type, d.outil), ("outil", "enchainer_commandes"))
        ouv = decider_prioritaire(d.arguments["etapes"][0])
        self.assertEqual(ouv.outil, "ouvrir_application")
        self.assertEqual(ouv.arguments, {"nom": "bloc-notes"})
        ecr = decider_prioritaire(d.arguments["etapes"][1])
        self.assertEqual(ecr.outil, "taper_texte")
        self.assertEqual(ecr.arguments["texte"], "Bonjour, je suis Jarvis, assistant intelligent.")
        self.assertNotIn("noter", {ouv.outil, ecr.outil})

    def test_le_texte_dicte_n_est_pas_decoupe_sur_et_ni_virgule(self):
        self.assertEqual(pc._decouper("écris Marie et Paul, ouvre la porte"), ["écris Marie et Paul, ouvre la porte"])
        self.assertEqual(pc._decouper("ouvre le bloc-notes puis écris bonjour puis appuie sur ctrl s"),
                         ["ouvre le bloc-notes", "écris bonjour", "appuie sur ctrl s"])
        self.assertEqual(pc._decouper("écris bonjour et enregistre-le"), ["écris bonjour", "enregistre-le"])

    def test_composition_libre_va_au_llm(self):
        # « écris UN texte » = le LLM doit composer : pas de route deterministe qui taperait « un texte ».
        self.assertIsNone(pc.router_commande_pc("Ouvre le Bloc-notes, écris un texte et enregistre-le."))

    def test_enregistre_le(self):
        self.assertEqual(pc._route_simple("enregistre-le"), ("appuyer_touches", {"combinaison": "ctrl+s"}))

    def test_exemples_du_cahier_des_charges(self):
        attendu = {
            "Ouvre Chrome.": ("ouvrir_navigateur", {"nom": "chrome"}),
            "Passe sur VS Code.": ("activer_fenetre", {"titre": "VS Code"}),
            "Clique sur Enregistrer.": ("cliquer_bouton", {"nom": "Enregistrer"}),
        }
        for phrase, (outil, args) in attendu.items():
            d = decider_prioritaire(phrase)
            self.assertEqual((d.outil, d.arguments), (outil, args), phrase)
        d = decider_prioritaire("Ouvre le Bloc-notes et écris Bonjour.")
        self.assertEqual(d.outil, "enchainer_commandes")
        self.assertEqual(d.arguments["etapes"][1], "écris Bonjour.")
        # Le point final de la dictée est du texte dicte : il reste dans l'argument tape.
        self.assertEqual(decider_prioritaire(d.arguments["etapes"][1]).arguments["texte"], "Bonjour.")

    def test_catalogue_llm_pour_bloc_notes(self):
        m = modules_pour_phrase(self.PHRASE)
        self.assertIn("controle_pc", m)
        self.assertIn("apps", m)
        self.assertNotIn("notes", m)             # « Bloc-notes » n'est pas la prise de notes de Jarvis
        self.assertIn("notes", modules_pour_phrase("prends une note : acheter du lait"))

    def test_taper_texte_et_noter_sont_distincts_dans_les_descriptions(self):
        import tools.notes  # noqa: F401
        self.assertIn("taper_texte", registre.get("noter").description)
        self.assertIn("PAS noter", registre.get("taper_texte").description)


class TestEnchainement(unittest.TestCase):
    def _outils(self, resultats, appels):
        def executer(outil_obj, args=None):
            appels.append((outil_obj.nom, dict(args or {})))
            return resultats.pop(0)
        return executer

    def test_le_texte_va_dans_l_application_ouverte_juste_avant(self):
        appels = []
        res = [ResultatOutil("bloc-notes est ouvert.", verifie=True), ResultatOutil("C'est tapé.", verifie=True)]
        with patch.object(registre, "executer", side_effect=self._outils(res, appels)), \
                patch.object(pc.time, "sleep"):
            r = pc.enchainer_commandes(["ouvre le bloc-notes", "écris Bonjour, ça va ?"])
        self.assertEqual(appels[0], ("ouvrir_application", {"nom": "bloc-notes"}))
        self.assertEqual(appels[1], ("taper_texte", {"texte": "Bonjour, ça va ?", "fenetre": "bloc-notes"}))
        self.assertTrue(r.succes and r.verifie)

    def test_arret_a_la_premiere_etape_en_echec(self):
        appels = []
        res = [ResultatOutil("J'ai lancé bloc-notes, mais je ne vois pas sa fenêtre apparaître.", succes=False)]
        with patch.object(registre, "executer", side_effect=self._outils(res, appels)), \
                patch.object(pc.time, "sleep"):
            r = pc.enchainer_commandes(["ouvre le bloc-notes", "écris Bonjour"])
        self.assertEqual([a[0] for a in appels], ["ouvrir_application"])     # la saisie n'a PAS eu lieu
        self.assertFalse(r.succes)
        self.assertNotIn("tapé", r)

    def test_echec_detecte_aussi_sur_un_outil_historique_en_texte_brut(self):
        appels = []
        res = ["Je ne trouve pas d'application « zzz » sur ce PC."]
        with patch.object(registre, "executer", side_effect=self._outils(res, appels)), \
                patch.object(pc.time, "sleep"):
            r = pc.enchainer_commandes(["passe sur zzz", "écris Bonjour"])
        self.assertEqual(len(appels), 1)
        self.assertFalse(r.succes)

    def test_etape_a_confirmation_stoppe_la_chaine(self):
        with patch.object(registre, "get", return_value=types.SimpleNamespace(confirmation=True, nom="x")), \
                patch.object(registre, "executer") as ex:
            r = pc.enchainer_commandes(["ouvre le bloc-notes"])
        ex.assert_not_called()
        self.assertIn("confirmation", r)

    def test_est_echec(self):
        self.assertTrue(est_echec("Je ne vois pas de bouton « OK »."))
        self.assertFalse(est_echec("Chrome est ouvert."))
        self.assertTrue(est_echec(ResultatOutil("x", succes=False)))
        self.assertFalse(est_echec(ResultatOutil("Je ne trouve pas", succes=True)))


class TestCliquer(unittest.TestCase):
    def _souris(self, place=True, position=(50, 60)):
        modsouris = types.SimpleNamespace(
            _BOUTONS={"gauche": (2, 4)}, _placer_curseur=MagicMock(return_value=place), _user32=MagicMock())
        return modsouris

    def test_clic_avec_curseur_verifie(self):
        sm = self._souris()
        with patch.dict("sys.modules", {"tools.souris": sm}), \
                patch.object(pc, "_fenetre_cible", return_value=FENETRES[1]), \
                patch.object(pc, "_controles", return_value=[("bouton", "Enregistrer", 50, 60)]), \
                patch.object(pc, "_position", return_value=(50, 60)), patch.object(pc.time, "sleep"):
            r = pc.cliquer_bouton("Enregistrer")
        self.assertTrue(r.succes)
        self.assertTrue(r.details["curseur_verifie"])
        self.assertFalse(r.verifie)               # l'EFFET du clic n'est pas constate : on ne le pretend pas
        self.assertEqual(sm._user32.mouse_event.call_count, 2)

    def test_pas_de_clic_si_le_curseur_n_est_pas_arrive(self):
        sm = self._souris()
        with patch.dict("sys.modules", {"tools.souris": sm}), \
                patch.object(pc, "_fenetre_cible", return_value=FENETRES[1]), \
                patch.object(pc, "_controles", return_value=[("bouton", "Enregistrer", 50, 60)]), \
                patch.object(pc, "_position", return_value=(400, 400)), patch.object(pc.time, "sleep"):
            r = pc.cliquer_bouton("Enregistrer")
        self.assertFalse(r.succes)
        sm._user32.mouse_event.assert_not_called()

    def test_curseur_non_deplace(self):
        sm = self._souris(place=False)
        with patch.dict("sys.modules", {"tools.souris": sm}), \
                patch.object(pc, "_fenetre_cible", return_value=FENETRES[1]), \
                patch.object(pc, "_controles", return_value=[("bouton", "Enregistrer", 50, 60)]):
            r = pc.cliquer_bouton("Enregistrer")
        self.assertFalse(r.succes)
        sm._user32.mouse_event.assert_not_called()

    def test_actions_sensibles_toujours_refusees(self):
        with patch.object(pc, "_fenetre_cible", return_value=FENETRES[1]), \
                patch.object(pc, "_controles", return_value=[("bouton", "Payer", 1, 1)]):
            self.assertIn("sans ta confirmation", pc.cliquer_bouton("Payer"))


class TestSecuritePreservee(unittest.TestCase):
    def test_niveaux_de_permission_inchanges(self):
        import tools.astra_pc  # noqa: F401
        import tools.apps  # noqa: F401
        self.assertEqual(registre.niveau("controle_pc_astra"), "N3")
        self.assertEqual(registre.niveau("ajouter_app"), "N3")
        for nom in ("taper_texte", "activer_fenetre", "lancer_application_pc", "cliquer_bouton"):
            self.assertFalse(registre.get(nom).mcp_expose, nom)

    def test_ctrl_alt_suppr_refuse(self):
        with patch.object(pc, "_appuyer") as p:
            r = pc.appuyer_touches("ctrl+alt+suppr")
        p.assert_not_called()
        self.assertFalse(r.succes)

    def test_dll_absente_import_possible(self):
        self.assertTrue(hasattr(pc, "EST_WINDOWS"))
        if not hasattr(ctypes, "windll") or pc.user32 is None:
            with self.assertRaises(OSError):
                pc._fenetres()


if __name__ == "__main__":
    unittest.main()
