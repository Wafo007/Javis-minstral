"""Worker de mission : processus detache qui execute la boucle d'agent (voir core/missions.py).

Usage : python scripts/mission_worker.py mission_001 [--racine DOSSIER]
Independant de la fenetre de chat et de Jarvis ; arretable via l'outil « mission_annuler » (drapeau en base)
ou le kill de son arbre de processus ; sa progression est dans <racine>/reports/<id>/execution.log.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import mission_agent  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("mission")
    p.add_argument("--racine", default=None)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    statut = mission_agent.executer_mission(a.racine, a.mission)
    print(f"{a.mission} : {statut}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
