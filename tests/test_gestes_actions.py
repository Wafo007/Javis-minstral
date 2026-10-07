"""Tests purs des raccourcis déclenchés par les gestes."""
import unittest

from core.gestes import _navigation_horizontale, _raccourci_zoom
from tools.souris import _coordonnees_pointeur


class NavigationGestesTests(unittest.TestCase):
    def test_navigation_par_defaut_reste_dans_application_active(self):
        self.assertEqual(
            _navigation_horizontale("suivant"),
            ("ctrl+tab", "🗂 Onglet suivant"),
        )
        self.assertEqual(
            _navigation_horizontale("precedent"),
            ("ctrl+shift+tab", "🗂 Onglet précédent"),
        )

    def test_ancien_alt_tab_reste_disponible_par_configuration(self):
        self.assertEqual(
            _navigation_horizontale("suivant", "applications"),
            ("alt+tab", "🪟 Application suivante"),
        )
        self.assertEqual(
            _navigation_horizontale("precedent", "alt_tab"),
            ("alt+shift+tab", "🪟 Application précédente"),
        )

    def test_zoom_utilise_les_raccourcis_de_application_active(self):
        self.assertEqual(
            _raccourci_zoom("agrandir"),
            ("ctrl+=", "🔎 Zoom avant"),
        )
        self.assertEqual(
            _raccourci_zoom("reduire"),
            ("ctrl+-", "🔍 Zoom arrière"),
        )

    def test_position_normalisee_respecte_geometrie_du_moniteur(self):
        moniteur = {"left": -1920, "top": 0, "width": 1920, "height": 1080}
        self.assertEqual(_coordonnees_pointeur(0, 0, moniteur), (-1920, 0))
        self.assertEqual(_coordonnees_pointeur(1, 1, moniteur), (-1, 1079))
        with self.assertRaises(ValueError):
            _coordonnees_pointeur(1.1, 0.5, moniteur)


if __name__ == "__main__":
    unittest.main()
