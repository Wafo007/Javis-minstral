"""Mission d'exemple sur une COPIE du projet (dossier ./copie) : vrai git/worktree et vraie suite pytest ;
le LLM est une DOUBLURE scriptee (aucun appel Mistral/Gemini). Lancer depuis un dossier de travail contenant `copie/`."""
import json, sys
from pathlib import Path as _P; sys.path.insert(0, str(_P(__file__).resolve().parents[3]))
from pathlib import Path
from core import missions as M, mission_agent as MA
from core.fournisseurs_mission import GestionnaireFournisseurs

class Faux:
    nom = "mistral"
    def __init__(s, r): s.r = list(r)
    def completer(s, m): return (s.r.pop(0) if s.r else json.dumps({"action": "finish", "summary": "fin"})), 120

j = lambda **k: json.dumps(k)
test = '''"""Test ajoute par la mission : la phrase vide ne declenche aucune route prioritaire."""
from core.routage_intentions import decider_prioritaire


def test_phrase_vide_sans_route():
    assert decider_prioritaire("") is None
    assert decider_prioritaire("   ") is None
'''
old = '"""Renvoie une route déterministe commune au PC et aux satellites."""'
new = '"""Renvoie une route déterministe commune au PC et aux satellites (None si la phrase est vide ou inconnue)."""'
rep = [
    j(action="update_plan", plan=["chercher le routeur prioritaire", "documenter son contrat", "ajouter un test", "valider"]),
    j(action="search", pattern="def decider_prioritaire"),
    j(action="read_file", path="core/routage_intentions.py", start=28, end=34),
    j(action="replace_in_file", path="core/routage_intentions.py", old=old, new=new),
    j(action="write_file", path="tests/test_routage_exemple_mission.py", content=test),
    j(action="write_file", path="tests/test_routage_exemple_mission.py", content="def casse(:\n"),   # erreur volontaire
    j(action="validate"),                                                                      # doit etre REFUSEE
    j(action="write_file", path="tests/test_routage_exemple_mission.py", content=test),        # correction
    j(action="validate"),
    j(action="finish", summary="Contrat de decider_prioritaire documente et teste (phrase vide)."),
]
store = M.MissionStore("missions")
m = M.demarrer_mission("analyse ton code source et améliore ton système de routage des commandes", depot="copie",
                       store=store, lancer=False, duree_s=1200)
g = GestionnaireFournisseurs([Faux(rep)], dormir=lambda s: None)
print("statut:", MA.AgentMission(store, m["id"], g).executer())
print(Path(store.get(m["id"])["rapports"]).as_posix())
