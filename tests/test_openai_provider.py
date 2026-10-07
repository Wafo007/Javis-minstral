"""Tests sans reseau de l'adaptateur OpenAI Responses API."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import cloud
from core.llm import Bloc, OpenAIProvider


class _Responses:
    def __init__(self, reponse):
        self.reponse = reponse
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.reponse


class OpenAIProviderTests(unittest.TestCase):
    def _provider(self, reponse):
        p = OpenAIProvider.__new__(OpenAIProvider)
        p.modele = "gpt-6-astra"
        p.qualite = True
        p.client = SimpleNamespace(responses=_Responses(reponse))
        return p

    def test_appel_outil_est_adapte_pour_jarvis(self):
        sortie = SimpleNamespace(
            output_text="",
            output=[SimpleNamespace(
                type="function_call", call_id="call_42", name="allumer_lumiere",
                arguments=json.dumps({"piece": "bureau"}))],
            usage=None,
        )
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
        self.assertTrue(p.client.responses.kwargs["parallel_tool_calls"])
        self.assertFalse(p.client.responses.kwargs["store"])

    def test_resultat_outil_et_capture_sont_reinjectes(self):
        p = self._provider(SimpleNamespace(output_text="Fait.", output=[], usage=None))
        historique = [
            {"role": "assistant", "content": [
                Bloc("tool_use", id="call_1", name="capture_screen", input={})]},
            {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": "call_1",
                "content": [{"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": "YWJj"}}],
            }]},
        ]
        items = p._traduire(historique)
        self.assertEqual(items[0]["type"], "function_call")
        self.assertEqual(items[1]["type"], "function_call_output")
        self.assertTrue(items[2]["content"][0]["image_url"].startswith("data:image/jpeg;base64,"))

    def test_conversation_simple_n_envoie_pas_un_catalogue_vide(self):
        sortie = SimpleNamespace(output_text="Bonjour.", output=[], usage=None)
        p = self._provider(sortie)
        with patch("core.cloud.enregistrer_usage"):
            rep = p.repondre(
                "Tu es Jarvis.", [{"role": "user", "content": "Bonjour"}], [])
        self.assertEqual(rep.content[0].text, "Bonjour.")
        self.assertNotIn("tools", p.client.responses.kwargs)
        self.assertNotIn("parallel_tool_calls", p.client.responses.kwargs)

    def test_vision_peut_forcer_astra_meme_si_claude_est_le_provider_courant(self):
        sortie = SimpleNamespace(
            output=[SimpleNamespace(
                type="function_call", arguments=json.dumps({"action": "termine"}))],
            usage=None,
        )
        client = SimpleNamespace(responses=_Responses(sortie))
        schema = {"type": "object", "properties": {
            "action": {"type": "string"}}, "required": ["action"]}
        with patch("core.cloud.fournisseur", return_value="anthropic"), \
                patch("core.cloud.client_openai", return_value=client), \
                patch("core.cloud.enregistrer_usage"):
            action = cloud.decider_action_vision(
                "Operateur", "Observe", "YWJj", schema,
                nom_modele="gpt-6-astra", qualite=True,
                fournisseur_force="openai")
        self.assertEqual(action, {"action": "termine"})
        self.assertEqual(client.responses.kwargs["model"], "gpt-6-astra")
        self.assertEqual(client.responses.kwargs["reasoning"], {"effort": "high"})

    def test_lecture_vision_ponctuelle_n_expose_aucun_outil(self):
        sortie = SimpleNamespace(output_text="Une erreur est affichée.", output=[], usage=None)
        client = SimpleNamespace(responses=_Responses(sortie))
        with patch("core.cloud.fournisseur", return_value="openai"), \
                patch("core.cloud.modele", return_value="gpt-5.6-terra"), \
                patch("core.cloud.client_openai", return_value=client), \
                patch("core.cloud.enregistrer_usage"):
            texte = cloud.repondre_vision("Lis l'écran", "Quelle erreur ?", "YWJj")
        self.assertEqual(texte, "Une erreur est affichée.")
        self.assertEqual(client.responses.kwargs["model"], "gpt-5.6-terra")
        self.assertNotIn("tools", client.responses.kwargs)
        self.assertFalse(client.responses.kwargs["store"])


if __name__ == "__main__":
    unittest.main()
