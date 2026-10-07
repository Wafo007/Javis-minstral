"""Tests sans reseau de l'adaptateur Mistral OpenAI-compatible."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import cloud
from core.llm import Bloc, MistralProvider


class _ChatCompletions:
    def __init__(self, reponse):
        self.reponse = reponse
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.reponse


class MistralProviderTests(unittest.TestCase):
    def _provider(self, reponse):
        p = MistralProvider.__new__(MistralProvider)
        p.modele = "mistral-small-latest"
        p.qualite = False
        p.client = SimpleNamespace(chat=SimpleNamespace(
            completions=_ChatCompletions(reponse)))
        return p

    def test_appel_outil_est_converti_en_format_interne(self):
        message = SimpleNamespace(
            content=None,
            tool_calls=[SimpleNamespace(
                id="call_42",
                function=SimpleNamespace(
                    name="allumer_lumiere",
                    arguments=json.dumps({"piece": "bureau"})))])
        sortie = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)
        p = self._provider(sortie)
        with patch("core.cloud.enregistrer_usage"):
            rep = p.repondre(
                "Tu es Jarvis.", [{"role": "user", "content": "Allume le bureau"}],
                [{"name": "allumer_lumiere", "description": "Lumiere",
                  "input_schema": {"type": "object", "properties": {}}}],
            )
        self.assertEqual(rep.stop_reason, "tool_use")
        self.assertEqual(rep.content[0].name, "allumer_lumiere")
        self.assertEqual(rep.content[0].input, {"piece": "bureau"})
        self.assertTrue(p.client.chat.completions.kwargs["parallel_tool_calls"])

    def test_reponse_texte_simple(self):
        message = SimpleNamespace(content="Bonjour.", tool_calls=[])
        sortie = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)
        p = self._provider(sortie)
        with patch("core.cloud.enregistrer_usage"):
            rep = p.repondre("Tu es Jarvis.", [{"role": "user", "content": "Bonjour"}], [])
        self.assertEqual(rep.stop_reason, "end")
        self.assertEqual(rep.content[0].text, "Bonjour.")
        self.assertNotIn("tools", p.client.chat.completions.kwargs)

    def test_historique_outil_est_converti_en_roles_openai(self):
        historique = [
            {"role": "assistant", "content": [
                Bloc("tool_use", id="call_1", name="capture_screen", input={})]},
            {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "call_1", "content": "ok"
            }]},
        ]
        messages = MistralProvider.__new__(MistralProvider)._traduire("systeme", historique)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["tool_calls"][0]["function"]["name"], "capture_screen")
        self.assertEqual(messages[2]["role"], "tool")
        self.assertEqual(messages[2]["tool_call_id"], "call_1")


if __name__ == "__main__":
    unittest.main()
