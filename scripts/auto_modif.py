"""Ligne de commande de l'auto-modification encadree (voir core/auto_modification.py).

  uv run python scripts/auto_modif.py demarrer <nom>
  uv run python scripts/auto_modif.py diff
  uv run python scripts/auto_modif.py valider
  uv run python scripts/auto_modif.py enregistrer "message"
  uv run python scripts/auto_modif.py annuler
  uv run python scripts/auto_modif.py terminer

Aucune fusion automatique : la branche jarvis/auto-... reste a relire.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import auto_modification as am  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "demarrer":
            print("Branche :", am.demarrer(RACINE, " ".join(args) or "modif")["branche"])
        elif cmd == "diff":
            print(am.diff(RACINE))
        elif cmd == "valider":
            ok, sortie = am.valider(RACINE)
            print(sortie)
            print("TESTS :", "OK" if ok else "ECHEC")
            return 0 if ok else 1
        elif cmd == "enregistrer":
            print("Commit :", am.enregistrer(RACINE, " ".join(args) or "auto-modification"))
        elif cmd == "annuler":
            am.annuler(RACINE)
            print("Retour a l'etat de depart effectue.")
        elif cmd == "terminer":
            am.terminer(RACINE)
            print("Session fermee. Relis la branche avant toute fusion.")
        else:
            print(__doc__)
            return 2
    except am.ErreurAutoModif as exc:
        print("Refuse :", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
