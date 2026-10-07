"""Tests hors matériel de la sortie audio du client satellite."""
import os
import unittest
from unittest.mock import patch

from satellite_pi import jarvis_satellite


class SatelliteAudioTests(unittest.TestCase):
    def test_pcm_alsa_partage_utilise_aplay_sans_shell(self):
        ancien = jarvis_satellite.CONF
        jarvis_satellite.CONF = {}
        try:
            with patch.dict(os.environ, {
                    "JARVIS_ALSA_OUTPUT_PCM": "jarvis_audio",
                    "JARVIS_ALSA_CONFIG_PATH": "/etc/asound.conf",
                 }), patch.object(jarvis_satellite.subprocess, "run") as lancer:
                self.assertTrue(
                    jarvis_satellite._jouer_alsa_partage(b"\0\0" * 160, 16000))
        finally:
            jarvis_satellite.CONF = ancien

        commande = lancer.call_args.args[0]
        self.assertEqual(commande[0], "aplay")
        self.assertIn("--device=jarvis_audio", commande)
        self.assertNotIn("shell", lancer.call_args.kwargs)
        self.assertEqual(
            lancer.call_args.kwargs["env"]["ALSA_CONFIG_PATH"],
            "/etc/asound.conf",
        )

    def test_absence_de_pcm_conserve_la_sortie_portaudio(self):
        ancien = jarvis_satellite.CONF
        jarvis_satellite.CONF = {}
        try:
            with patch.dict(os.environ, {}, clear=True):
                self.assertFalse(
                    jarvis_satellite._jouer_alsa_partage(b"\0\0", 16000))
        finally:
            jarvis_satellite.CONF = ancien


if __name__ == "__main__":
    unittest.main()
