"""Enregistrement des cibles AUTORISEES de l'audit de securite Jarvis (jamais a la voix).

  python scripts/security_cible.py add http://127.0.0.1:3000 --attestation "Juice Shop lance par moi" [--duree-h 8] [--ports 3000] [--actions web api reseau outils] [--proprietaire]
  python scripts/security_cible.py code C:\\chemin\\vers\\mon\\projet
  python scripts/security_cible.py list
  python scripts/security_cible.py revoke <id|hote>
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modes.ghost_protocol.security import service                      # noqa: E402
from modes.ghost_protocol.security.perimetre import RefusPerimetre    # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("add")
    a.add_argument("url")
    a.add_argument("--attestation", default="")
    a.add_argument("--duree-h", type=float, default=24)
    a.add_argument("--ports", type=int, nargs="*")
    a.add_argument("--actions", nargs="*")
    a.add_argument("--proprietaire", action="store_true", help="je confirme etre proprietaire/autorise par ecrit (hote externe)")
    c = sp.add_parser("code")
    c.add_argument("chemin")
    c.add_argument("--attestation", default="")
    sp.add_parser("list")
    r = sp.add_parser("revoke")
    r.add_argument("cible")
    args = ap.parse_args(argv)
    reg = service().registre
    try:
        if args.cmd == "add":
            t = reg.enregistrer(args.url, args.attestation, args.duree_h, args.ports, args.actions, args.proprietaire)
            print(f"Cible enregistree : {t.id} {t.schema}://{t.hote} ports {t.ports} ({t.type}) valable jusqu'a {time.strftime('%d/%m %H:%M', time.localtime(t.expire))}")
        elif args.cmd == "code":
            t = reg.enregistrer_code(args.chemin, args.attestation)
            print(f"Dossier de code enregistre : {t.id} ({t.chemin_code})")
        elif args.cmd == "list":
            for t in reg.lister():
                ok, raison = t.valide(time.time())
                print(f"{t.id}  {t.type:<15} {t.hote}:{t.ports}  {'ACTIVE' if ok else 'INACTIVE (' + raison + ')'}")
        else:
            print(f"{reg.revoquer(args.cible)} cible(s) revoquee(s).")
    except RefusPerimetre as e:
        print("REFUSE :", e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
