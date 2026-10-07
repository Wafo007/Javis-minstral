"""Test rapide de l'acces Instagram (sans la voix), pour un ou plusieurs comptes.

Lance-le avec :  uv run python tester_instagram.py
Verifie chaque token, affiche abonnes + vues d'une video, puis le resume Jarvis.
"""
from core import registre
registre.charger_outils()
from tools import instagram as ig

comptes = ig._comptes()
if not comptes:
    print("Aucun compte Instagram configure (instagram.comptes dans config.yaml).")
    raise SystemExit(1)

print(f"{len(comptes)} compte(s) configure(s).\n")
for c in comptes:
    print(f"=== {c['nom']} (id {c['user_id']}) ===")
    try:
        infos = ig._get(c["user_id"], c["token"], fields="username,followers_count,media_count")
        print(f"  OK (via {ig._HOTE}) -> @{infos.get('username')} : "
              f"{infos.get('followers_count')} abonnes, {infos.get('media_count')} publications")
    except Exception as e:
        print(f"  Echec : {e}")
        print("  -> token expire / mauvaises permissions (voir docs/instagram.md).")
        continue
    try:
        medias = ig._get(f"{c['user_id']}/media", c["token"],
                         fields="id,media_type,caption", limit=5).get("data", [])
        for m in medias:
            if m.get("media_type") in ("VIDEO", "REELS"):
                v = ig._vues_media(m["id"], c["token"])
                print(f"  video \"{(m.get('caption','') or '')[:30]}\" -> vues : {v}")
                break
    except Exception as e:
        print(f"  Insights indisponibles : {e}")

print("\nResume Jarvis (tous comptes) :")
print(" ", ig.instagram_resume())
