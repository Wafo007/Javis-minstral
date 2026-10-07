"""Point d'entrée de la commande ``jarvis-vocal``."""
from pathlib import Path
import runpy


def main() -> None:
    script = Path(__file__).resolve().parents[2] / "jarvis14.py"
    if not script.exists():
        raise SystemExit(
            "jarvis14.py est introuvable. Lance Jarvis depuis le dossier du projet.")
    runpy.run_path(str(script), run_name="__main__")
