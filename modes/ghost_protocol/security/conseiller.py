"""CONSEILLER IA (facultatif). Le LLM ne fait que PROPOSER : liste blanche d'etapes et texte de synthese. Il ne decide jamais d'un statut,
d'une action hors perimetre ni d'une commande. Sans LLM, l'audit est identique (100 % deterministe). Aucune donnee sensible n'est envoyee :
uniquement des compteurs et titres de constats, jamais de secrets/en-tetes/corps de reponse."""
from __future__ import annotations

import json
import re
import threading

DELAI_S = 25.0


def _appel(systeme: str, question: str, delai: float = DELAI_S) -> str:
    """Appelle le routeur LLM existant dans un fil avec delai maximal. Leve TimeoutError/RuntimeError si indisponible."""
    sortie = {}

    def _fil():
        try:
            from core.llm import llm
            r = llm().repondre(systeme, [{"role": "user", "content": question}], [])
            sortie["t"] = "".join(getattr(b, "text", "") or "" for b in (r.content or []) if getattr(b, "type", "") == "text")
        except Exception as e:           # LLM non configure, hors ligne, etc.
            sortie["e"] = e
    t = threading.Thread(target=_fil, daemon=True)
    t.start()
    t.join(delai)
    if t.is_alive():
        raise TimeoutError("LLM trop lent")
    if "e" in sortie:
        raise RuntimeError(type(sortie["e"]).__name__)
    return sortie.get("t", "")


class ConseillerLLM:
    def __init__(self, appel=_appel):
        self._appel = appel

    def proposer(self, faits: dict, disponibles: list) -> list:
        resume = {"technologies": faits.get("technologies", [])[:8], "api": bool(faits.get("a_api")), "ports_ouverts": faits.get("ports_ouverts", [])[:10]}
        txt = self._appel("Tu conseilles un audit de securite AUTORISE sur un laboratoire. Reponds uniquement par un tableau JSON de noms d'etapes "
                          f"choisis parmi {disponibles}.", json.dumps(resume, ensure_ascii=False))
        m = re.search(r"\[.*?\]", txt, re.S)
        liste = json.loads(m.group(0)) if m else []
        return [x for x in liste if isinstance(x, str) and x in disponibles]       # liste blanche stricte

    def resumer(self, faits: dict, synthese: dict) -> str:
        txt = self._appel("Redige en francais un resume executif de 4 phrases maximum, factuel, base uniquement sur les compteurs fournis. "
                          "N'invente aucune vulnerabilite.", json.dumps(synthese, ensure_ascii=False, default=str)[:3000])
        return txt.strip()
