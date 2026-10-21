import importlib.util
import unittest
from pathlib import Path

import yaml

_spec = importlib.util.spec_from_file_location(
    "adapter_config", Path(__file__).resolve().parent.parent / "scripts" / "adapter_config.py")
adapter_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter_config)


class AdapterConfigTest(unittest.TestCase):
    def test_garde_les_reglages_et_vide_les_placeholders(self):
        cfg = yaml.safe_load("cloud: {fournisseur: mistral}\nmistral: {cle: SECRET, modele: mistral-small-latest}\n"
                             "openai: {cle: 'sk-proj-...'}\nanthropic: {cle: 'sk-ant-...'}\nastra_pc: {modele: gpt-6-astra}\n")
        adapter_config.adapter(cfg)
        self.assertEqual(cfg["mistral"]["cle"], "SECRET")
        self.assertEqual(cfg["mistral"]["modele"], "mistral-small-latest")
        self.assertEqual(cfg["openai"]["cle"], "")
        self.assertEqual(cfg["anthropic"]["cle"], "")
        self.assertEqual(cfg["astra_pc"]["fournisseur"], "mistral")
        self.assertEqual(cfg["astra_pc"]["modele"], "gpt-6-astra")

    def test_idempotent_et_vraie_cle_openai_conservee(self):
        cfg = yaml.safe_load("openai: {cle: sk-proj-abcdef123}\n")
        adapter_config.adapter(cfg)
        self.assertEqual(cfg["openai"]["cle"], "sk-proj-abcdef123")
        self.assertEqual(adapter_config.adapter(cfg), [])


if __name__ == "__main__":
    unittest.main()
