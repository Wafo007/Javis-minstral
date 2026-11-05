"""Appairage et diagnostic du telephone Android (debogage sans fil) -- voir docs/mobile_android.md.

  python scripts/mobile_appairer.py pair  192.168.x.x:PORT_APPAIRAGE  CODE6   (une seule fois)
  python scripts/mobile_appairer.py connect 192.168.x.x:PORT_CONNEXION        (a chaque changement de Wi-Fi/redemarrage)
  python scripts/mobile_appairer.py diag                                       (verifie tout : adb, appareil, batterie, ecran)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import reglage  # noqa: E402
from core.mobile_adb import Adb, ErreurMobile  # noqa: E402


def main(argv):
    adb = Adb(adb=str(reglage("mobile.adb_chemin", "") or "") or None, appareil=str(reglage("mobile.appareil", "") or ""))
    try:
        if len(argv) >= 3 and argv[0] == "pair":
            print(adb.appairer(argv[1], argv[2]))
            print("Appairage OK. Ensuite : connect <ip:port de connexion> (autre port, affiche sur l'ecran « Debogage sans fil »).")
        elif len(argv) >= 2 and argv[0] == "connect":
            print(adb.connecter(argv[1]))
            print(f"Mets  mobile.appareil: '{argv[1]}'  dans config.yaml pour que Jarvis se reconnecte seul.")
        elif argv and argv[0] == "diag":
            print("Appareils :", adb.appareils() or "aucun")
            s = adb.statut()
            print(f"OK : {s['modele']} Android {s['android']}, batterie {s.get('niveau')} %, ecran allume={s.get('ecran_allume')}")
        else:
            print(__doc__)
            return 2
    except ErreurMobile as exc:
        print("ECHEC :", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
