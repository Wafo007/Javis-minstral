"""Audit de securite AUTORISE en ligne de commande (memes moteurs que la voix et le HUD).

  python scripts/security_audit.py outils                      # detection honnete des outils (operationnel / absent / non integrable)
  python scripts/security_audit.py run http://127.0.0.1:3000   # audit complet d'une cible deja enregistree
  python scripts/security_audit.py run --code C:\\mon\\projet   # audit statique d'un dossier enregistre
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modes.ghost_protocol.security import outils as O, service     # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("outils")
    r = sp.add_parser("run")
    r.add_argument("cible")
    r.add_argument("--code", action="store_true")
    r.add_argument("--sans-pdf", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "outils":
        for n, o in O.detecter().items():
            print(f"{n:<18} {o.statut:<14} {o.version or ''} {o.note or ''}")
        return 0
    svc = service()
    a = svc.audit
    a.pdf = not args.sans_pdf
    ok, msg = a.preparer(args.cible, code=args.code)
    print(msg)
    if not ok:
        return 2
    a.lancer("complet", attendre=True)
    for e in a.session["etapes"]:
        print(f"  {e['statut']:<9} {e['cle']:<12} {e['resume']}")
    s = a.snapshot()
    print(f"Etat {s['etat']} : {s['confirmes']} confirmes, {s['potentiels']} a verifier/reproduits, {s['total']} au total.")
    for k, v in a.rapports.items():
        print(f"  rapport {k} : {v}")
    return 0 if a.etat == "TERMINÉ" else 1


if __name__ == "__main__":
    sys.exit(main())
