import unittest

import numpy as np

from gestes.regard import (
    CalibrationRegard,
    DetecteurSourcils,
    _projection,
    construire_profil_sourcils,
    filtrer_mesures,
    lisser_pointeur,
    niveau_sourcils,
    score_clignement,
    score_sourcils,
)


class TestCalibrationRegard(unittest.TestCase):
    def test_projection_sur_segment(self):
        self.assertAlmostEqual(_projection((5, 2), (0, 2), (10, 2)), 0.5)

    def test_ajustement_retrouve_une_relation_reguliere(self):
        rng = np.random.default_rng(7)
        observations = rng.normal(size=(80, 13))
        cibles = np.column_stack((
            0.50 + 0.16 * observations[:, 0]
            + 0.13 * observations[:, 3]
            + 0.025 * observations[:, 0] * observations[:, 3],
            0.50 + 0.12 * observations[:, 1]
            + 0.09 * observations[:, 4]
            + 0.02 * observations[:, 1] * observations[:, 4],
        ))
        cibles = np.clip(cibles, 0.0, 1.0)
        calibration = CalibrationRegard.ajuster(observations, cibles)
        erreur = np.mean([
            np.linalg.norm(calibration.predire(obs) - cible)
            for obs, cible in zip(observations, cibles)
        ])
        self.assertLess(erreur, 0.04)

    def test_lissage_bloque_le_micro_tremblement(self):
        precedent = np.asarray([500.0, 400.0])
        np.testing.assert_array_equal(
            lisser_pointeur(precedent, [502.0, 401.0], 2200.0), precedent)

    def test_lissage_reagit_plus_vite_aux_grands_deplacements(self):
        precedent = np.asarray([0.0, 0.0])
        petit = lisser_pointeur(precedent, [100.0, 0.0], 2200.0)[0]
        grand = lisser_pointeur(precedent, [1000.0, 0.0], 2200.0)[0]
        self.assertGreater(grand / 1000.0, petit / 100.0)

    def test_filtre_ecarte_une_mesure_aberrante(self):
        normales = np.ones((12, 13))
        valeurs = np.vstack((normales, np.full((1, 13), 50.0)))
        filtrees = filtrer_mesures(valeurs)
        self.assertEqual(len(filtrees), 12)
        self.assertLess(float(np.max(filtrees)), 2.0)

    def test_correction_locale_rapproche_une_ancre_de_sa_cible(self):
        rng = np.random.default_rng(11)
        observations = rng.normal(size=(60, 13))
        cibles = np.clip(np.column_stack((
            0.5 + 0.12 * observations[:, 0],
            0.5 + 0.12 * observations[:, 1],
        )), 0.0, 1.0)
        ancres = observations[:16]
        cibles_ancres = cibles[:16].copy()
        cibles_ancres[:, 0] += 0.04
        sans = CalibrationRegard.ajuster(observations, cibles)
        avec = CalibrationRegard.ajuster(
            observations, cibles, ancres, cibles_ancres)
        erreur_sans = np.linalg.norm(
            sans.predire(ancres[0]) - cibles_ancres[0])
        erreur_avec = np.linalg.norm(
            avec.predire(ancres[0]) - cibles_ancres[0])
        self.assertLess(erreur_avec, erreur_sans)


class TestDetecteurSourcils(unittest.TestCase):
    PROFIL = {"retour": 0.18, "garde": 0.28, "seuil": 0.50}

    def test_clignement_prend_le_plus_ferme_des_deux_yeux(self):
        self.assertAlmostEqual(score_clignement({
            "eyeBlinkLeft": 0.2,
            "eyeBlinkRight": 0.8,
        }), 0.8)

    def test_score_moyenne_interieur_et_exterieurs(self):
        self.assertAlmostEqual(score_sourcils({
            "browInnerUp": 0.9,
            "browOuterUpLeft": 0.6,
            "browOuterUpRight": 0.3,
        }), 0.6)

    def test_progression_personnelle_va_du_neutre_aux_sourcils_leves(self):
        neutre = np.asarray([0.03, 0.10])
        leves = np.asarray([0.43, 0.12])
        profil = construire_profil_sourcils(neutre, leves)
        self.assertAlmostEqual(niveau_sourcils(neutre, profil), 0.0)
        self.assertAlmostEqual(niveau_sourcils(leves, profil), 1.0)

    def test_ecart_geometrique_compense_un_modele_absent(self):
        neutre = np.asarray([0.0, 0.10])
        leves = np.asarray([0.0, 0.12])
        profil = construire_profil_sourcils(neutre, leves)
        self.assertTrue(bool(profil["fiables"][1]))
        self.assertGreater(niveau_sourcils(leves, profil), 0.9)

    def test_sourcils_tenus_declenchent_un_seul_clic(self):
        d = DetecteurSourcils(tenue_s=0.3, cooldown_s=0.6)
        self.assertIsNone(d.alimenter(0.7, self.PROFIL, 1.0))
        self.assertEqual(d.alimenter(0.7, self.PROFIL, 1.31), "clic_gauche")
        self.assertIsNone(d.alimenter(0.7, self.PROFIL, 2.0))

    def test_geste_trop_court_ne_clique_pas(self):
        d = DetecteurSourcils(tenue_s=0.3)
        self.assertIsNone(d.alimenter(0.7, self.PROFIL, 1.0))
        self.assertIsNone(d.alimenter(0.1, self.PROFIL, 1.2))

    def test_retour_neutre_rearme_apres_cooldown(self):
        d = DetecteurSourcils(tenue_s=0.1, cooldown_s=0.2)
        d.alimenter(0.7, self.PROFIL, 1.0)
        self.assertEqual(d.alimenter(0.7, self.PROFIL, 1.11), "clic_gauche")
        self.assertIsNone(d.alimenter(0.1, self.PROFIL, 1.2))
        self.assertIsNone(d.alimenter(0.7, self.PROFIL, 1.25))
        self.assertIsNone(d.alimenter(0.1, self.PROFIL, 1.31))
        self.assertIsNone(d.alimenter(0.7, self.PROFIL, 1.4))
        self.assertEqual(d.alimenter(0.7, self.PROFIL, 1.51), "clic_gauche")


if __name__ == "__main__":
    unittest.main()
