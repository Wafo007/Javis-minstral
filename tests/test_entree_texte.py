"""Tests sans micro ni reseau de la saisie clavier (entree texte, reponse toujours vocale)."""
import re
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import hud
from core import entree_texte

ROOT = Path(__file__).resolve().parent.parent


def _reglages(**valeurs):
    """Remplace core.entree_texte.reglage par un dictionnaire plat {'texte.actif': ...}."""
    return patch.object(entree_texte, "reglage",
                        side_effect=lambda cle, defaut=None: valeurs.get(cle, defaut))


class _Base(unittest.TestCase):
    def setUp(self):
        entree_texte.vider()
        entree_texte._dernier_envoi = 0.0   # pas de delai de debit entre deux tests

    def tearDown(self):
        entree_texte.vider()


class SoumissionTests(_Base):
    def test_texte_simple_arrive_dans_la_file_avec_son_origine(self):
        retenu = entree_texte.soumettre("  ouvre YouTube  ", origine="hud")
        self.assertEqual(retenu, "ouvre YouTube")
        entree = entree_texte.prendre(0.0)
        self.assertEqual((entree.texte, entree.origine), ("ouvre YouTube", "hud"))
        self.assertIsNone(entree_texte.prendre(0.0))

    def test_origine_inconnue_devient_hud(self):
        entree_texte.soumettre("bonjour", origine="pirate")
        self.assertEqual(entree_texte.prendre(0.0).origine, "hud")

    def test_nettoyage_des_caracteres_de_controle_et_des_retours_ligne(self):
        self.assertEqual(entree_texte.nettoyer("a\x00b\x07 c\n\n d\t e"), "ab c d e")

    def test_message_vide_ou_blanc_refuse(self):
        for vide in ("", "   ", "\n\t", None, "\x00\x01"):
            with self.subTest(vide=vide):
                with self.assertRaises(entree_texte.RefusEntree):
                    entree_texte.soumettre(vide)

    def test_message_trop_long_refuse(self):
        with _reglages(**{"texte.longueur_max": 50}):
            with self.assertRaises(entree_texte.RefusEntree):
                entree_texte.soumettre("x" * 51)
            self.assertEqual(entree_texte.soumettre("x" * 50), "x" * 50)

    def test_longueur_max_est_bornee(self):
        with _reglages(**{"texte.longueur_max": 999999}):
            self.assertEqual(entree_texte.longueur_max(), 4000)
        with _reglages(**{"texte.longueur_max": 1}):
            self.assertEqual(entree_texte.longueur_max(), 20)
        with _reglages(**{"texte.longueur_max": "n'importe quoi"}):
            self.assertEqual(entree_texte.longueur_max(), entree_texte.LONGUEUR_MAX_DEFAUT)

    def test_desactive_par_la_config(self):
        with _reglages(**{"texte.actif": False}):
            self.assertFalse(entree_texte.actif())
            with self.assertRaises(entree_texte.RefusEntree):
                entree_texte.soumettre("bonjour")
        self.assertFalse(entree_texte.en_attente())

    def test_envois_trop_rapproches_refuses(self):
        entree_texte.soumettre("un")
        with self.assertRaises(entree_texte.RefusEntree):
            entree_texte.soumettre("deux")

    def test_file_pleine_refusee_puis_liberee(self):
        for i in range(entree_texte.TAILLE_FILE_MAX):
            entree_texte._dernier_envoi = 0.0
            entree_texte.soumettre(f"message {i}")
        entree_texte._dernier_envoi = 0.0
        with self.assertRaises(entree_texte.RefusEntree):
            entree_texte.soumettre("de trop")
        self.assertEqual(entree_texte.vider(), entree_texte.TAILLE_FILE_MAX)
        self.assertFalse(entree_texte.en_attente())

    def test_ordre_premier_arrive_premier_servi(self):
        for mot in ("un", "deux", "trois"):
            entree_texte._dernier_envoi = 0.0
            entree_texte.soumettre(mot)
        self.assertEqual([entree_texte.prendre(0.0).texte for _ in range(3)], ["un", "deux", "trois"])

    def test_prendre_avec_attente_renvoie_none_a_l_echeance(self):
        debut = time.monotonic()
        self.assertIsNone(entree_texte.prendre(0.05))
        self.assertLess(time.monotonic() - debut, 1.0)


class ConfirmationEcriteTests(_Base):
    def test_n2_permis_par_defaut(self):
        with _reglages():
            self.assertTrue(entree_texte.confirmation_ecrite_permise("N2"))

    def test_n3_refuse_par_defaut_et_permis_si_choisi(self):
        with _reglages():
            self.assertFalse(entree_texte.confirmation_ecrite_permise("N3"))
        with _reglages(**{"texte.confirmation_ecrite_n3": True}):
            self.assertTrue(entree_texte.confirmation_ecrite_permise("N3"))

    def test_tout_refuse_si_confirmation_ecrite_desactivee_ou_saisie_coupee(self):
        with _reglages(**{"texte.confirmation_ecrite": False, "texte.confirmation_ecrite_n3": True}):
            self.assertFalse(entree_texte.confirmation_ecrite_permise("N2"))
            self.assertFalse(entree_texte.confirmation_ecrite_permise("N3"))
        with _reglages(**{"texte.actif": False}):
            self.assertFalse(entree_texte.confirmation_ecrite_permise("N2"))

    def test_delai_confirmation_borne(self):
        with _reglages(**{"texte.delai_confirmation": 1}):
            self.assertEqual(entree_texte.delai_confirmation(), 5.0)
        with _reglages(**{"texte.delai_confirmation": 9999}):
            self.assertEqual(entree_texte.delai_confirmation(), 120.0)
        with _reglages():
            self.assertEqual(entree_texte.delai_confirmation(), 20.0)


class HudTests(_Base):
    def test_action_ecrire_met_le_texte_en_file_sans_toucher_aux_reglages(self):
        with patch.object(hud, "_synchroniser_controles") as synchroniser:
            resultat = hud._appliquer_controle({"action": "ecrire", "texte": "allume la lumiere"})
        self.assertTrue(resultat["ok"])
        self.assertEqual(entree_texte.prendre(0.0).texte, "allume la lumiere")
        synchroniser.assert_not_called()

    def test_action_ecrire_refusee_renvoie_un_message(self):
        resultat = hud._appliquer_controle({"action": "ecrire", "texte": "   "})
        self.assertFalse(resultat["ok"])
        self.assertIn("vide", resultat["message"].lower())
        self.assertFalse(entree_texte.en_attente())

    def test_action_inconnue_toujours_refusee(self):
        self.assertFalse(hud._appliquer_controle({"action": "n_importe_quoi"})["ok"])

    def test_la_page_contient_le_champ_de_saisie_et_le_garde_fou_http(self):
        page = (ROOT / "hud.html").read_text(encoding="utf-8")
        self.assertIn('id="saisieTexte"', page)
        self.assertIn('action: "ecrire"', page)
        self.assertIn('"X-Jarvis-HUD": "1"', page)
        # Le texte tape est echappe a l'affichage (jamais injecte tel quel en HTML).
        self.assertIn("echap(ev.texte)", page)


class BranchementJarvis14Tests(unittest.TestCase):
    """jarvis14 est trop lourd a importer (micro, Whisper) : controle statique."""

    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "jarvis14.py").read_text(encoding="utf-8")

    def test_les_deux_entrees_passent_par_le_meme_coeur(self):
        self.assertIn("def _traiter_question(", self.source)
        self.assertIn('origine="voix")', self.source)
        self.assertIn('origine="texte")', self.source)
        self.assertEqual(len(re.findall(r"_traiter_question\(", self.source)), 3)  # def + 2 appels

    def test_la_boucle_principale_lit_la_file_avant_le_micro(self):
        boucle = self.source[self.source.index("suite = enchainer"):]
        self.assertLess(boucle.index("entree_texte.prendre(0.0)"), boucle.index("bloc = lire_bloc(flux)"))
        self.assertLess(boucle.index("entree_texte.prendre(0.0)"), boucle.index("_MICRO_MUET.is_set()"))

    def test_la_reponse_reste_vocale(self):
        coeur = self.source[self.source.index("def _traiter_question("):
                            self.source.index("def _feedback_geste(")]
        self.assertIn("repondre_en_ecoutant(", coeur)    # meme chemin : repondre() -> dire()
        self.assertIn("dire(texte)", coeur)
        self.assertNotIn("origine == \"texte\"", coeur.split("_confirmer(")[0])  # pas de branche muette

    def test_confirmation_ecrite_soumise_au_niveau_de_permission(self):
        confirmer = self.source[self.source.index("def _confirmer("):
                                self.source.index("def _tronquer(")]
        self.assertIn("confirmation_ecrite_permise(niveau_en_attente)", confirmer)
        self.assertIn("registre.niveau(registre.nom_en_attente()", confirmer)
        # La reponse ecrite passe par le meme interpreteur strict que la voix.
        self.assertIn("_est_oui(reponse)", confirmer)
        # Un « oui » tape pour un N3 (qui exige la voix) est jete, pas rejoue comme nouvelle demande.
        self.assertIn("entree_texte.vider()", confirmer)

    def test_une_demande_ecrite_coupe_la_fenetre_d_ecoute_de_suite(self):
        suite = self.source[self.source.index("def attendre_suite("):self.source.index("def repondre_en_ecoutant(")]
        self.assertIn("entree_texte.en_attente()", suite)


if __name__ == "__main__":
    unittest.main()
