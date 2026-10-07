"""Lance le prototype local de controle du pointeur par le regard."""
import subprocess
import sys
from pathlib import Path


RACINE = Path(__file__).resolve().parent.parent
PY = RACINE / "gestes" / ".venv-tracker" / "Scripts" / "python.exe"
SCRIPT = RACINE / "gestes" / "regard.py"


def main():
    if not PY.exists():
        print("Environnement gestes absent — lance d'abord : python scripts/setup_gestes.py")
        return 1
    return subprocess.call([str(PY), str(SCRIPT), *sys.argv[1:]], cwd=str(RACINE))


if __name__ == "__main__":
    raise SystemExit(main())
