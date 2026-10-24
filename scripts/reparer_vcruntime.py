"""Repare « DLL load failed / _greenlet » SANS installer Visual C++ (deploiement local des DLL).

Playwright depend de greenlet, qui a besoin de VCRUNTIME140.dll, VCRUNTIME140_1.dll et MSVCP140.dll.
Quand le redistribuable Microsoft ne s'installe pas, on peut copier ces DLL a cote de Python : Windows les
charge depuis le dossier de l'application (deploiement « app-local », autorise par Microsoft).

  uv run python scripts/reparer_vcruntime.py            # diagnostic seul (ne modifie rien)
  uv run python scripts/reparer_vcruntime.py --copier   # copie les DLL manquantes trouvees ailleurs

Jarvis fonctionne de toute facon SANS Playwright (pilotage CDP direct, core/cdp_leger.py) : ce script
n'est utile que pour retrouver Playwright (reservation, PDF du Signal du matin).
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

DLLS = ("VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "MSVCP140.dll")
LIEUX = [os.environ.get(v, "") for v in ("SystemRoot",)]


def _candidats(nom):
    """Copies de la DLL deja presentes sur le disque (Windows, applications qui l'embarquent)."""
    racines = [Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32",
               Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
               Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
               Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
               Path(r"C:\laragon"), Path(r"C:\Program Files\Google\Chrome\Application")]
    vus = []
    for racine in racines:
        if not racine or not racine.exists():
            continue
        if racine.name.lower() == "system32":
            c = racine / nom
            if c.exists():
                vus.append(c)
            continue
        try:
            for c in racine.rglob(nom):
                if len(vus) < 12:
                    vus.append(c)
        except OSError:
            continue
    return vus


def _est_64(chemin: Path) -> bool:
    try:
        with open(chemin, "rb") as f:
            f.seek(0x3C)
            pe = int.from_bytes(f.read(4), "little")
            f.seek(pe + 4)
            return int.from_bytes(f.read(2), "little") == 0x8664
    except OSError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--copier", action="store_true", help="copier les DLL manquantes a cote de Python et de greenlet")
    args = ap.parse_args(argv)
    if os.name != "nt":
        print("Windows uniquement.")
        return 3
    cibles = {Path(sys.executable).parent}
    try:
        import greenlet
        cibles.add(Path(greenlet.__file__).parent)
    except Exception as exc:
        import importlib.util
        spec = importlib.util.find_spec("greenlet")
        print(f"[!] import greenlet : {type(exc).__name__}: {exc}")
        if spec and spec.submodule_search_locations:
            cibles.add(Path(list(spec.submodule_search_locations)[0]))
    systeme = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    print("Dossiers cibles :", *[str(c) for c in cibles], sep="\n  ")
    manquantes = []
    for nom in DLLS:
        dans_sys = (systeme / nom).exists()
        locale = any((c / nom).exists() for c in cibles)
        print(f"{'OK    ' if dans_sys or locale else 'ABSENT'} {nom}  (System32 : {'oui' if dans_sys else 'non'}, "
              f"local : {'oui' if locale else 'non'})")
        if not (dans_sys or locale):
            manquantes.append(nom)
    if not manquantes:
        print("\nLes trois DLL sont presentes : le probleme est ailleurs. Lance :\n"
              "  uv run python -c \"import greenlet._greenlet\"\net envoie-moi le message complet.")
        return 0
    if not args.copier:
        print("\nDLL manquantes :", ", ".join(manquantes), "\nRelance avec --copier pour les chercher et les copier.")
        return 1
    for nom in manquantes:
        sources = [c for c in _candidats(nom) if _est_64(c)]
        if not sources:
            print(f"[x] {nom} : aucune copie 64 bits trouvee sur ce PC.")
            continue
        source = max(sources, key=lambda c: c.stat().st_mtime)      # la plus recente
        for cible in cibles:
            try:
                shutil.copy2(source, cible / nom)
                print(f"[ok] {nom} copie depuis {source} vers {cible}")
            except OSError as exc:
                print(f"[x] {nom} -> {cible} : {exc}")
    print("\nRelance : uv run python -c \"import greenlet._greenlet; print('greenlet OK')\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
