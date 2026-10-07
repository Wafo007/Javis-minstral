"""Reconnaissance musicale via shazamio — tourne dans le venv ISOLÉ Python 3.12.

    python reconnaisseur.py <chemin_audio>

Sort UN objet JSON sur stdout :
  { "ok": true, "titre": ..., "artiste": ..., "album": ..., "annee": ...,
    "genre": ..., "url": ... }
  ou { "ok": false, "message": "..." }

Pourquoi un process séparé ? shazamio-core (le moteur d'empreinte, en Rust) n'a
PAS de wheel Python 3.13 sous Windows (comme MediaPipe). Il vit donc dans
musique/.venv-shazam (Python 3.12). Le process principal (3.13) capture l'audio et
appelle ce script. **Rien d'autre que l'empreinte des ~8 s capturées ne part vers
Shazam** — pas le micro en continu, pas de métadonnées perso.
"""
import asyncio
import json
import sys

for _f in (sys.stdout, sys.stderr):          # console Windows cp1252 -> UTF-8
    try:
        _f.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _meta_song(track):
    """Extrait album / année / etc. des sections 'SONG' de la réponse Shazam."""
    meta = {}
    for s in (track.get("sections") or []):
        if s.get("type") == "SONG":
            for m in (s.get("metadata") or []):
                if m.get("title"):
                    meta[m["title"]] = m.get("text", "")
    return meta


async def _reconnaitre(chemin):
    from shazamio import Shazam
    out = await Shazam().recognize(chemin)
    track = (out or {}).get("track") or {}
    if not track:
        return {"ok": False, "message": "aucune correspondance"}
    meta = _meta_song(track)
    return {
        "ok": True,
        "titre": track.get("title"),
        "artiste": track.get("subtitle"),
        "album": meta.get("Album"),
        "annee": meta.get("Released") or meta.get("Year"),
        "genre": (track.get("genres") or {}).get("primary"),
        "url": track.get("url"),
    }


async def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "message": "chemin manquant"}))
        return
    try:
        res = await _reconnaitre(sys.argv[1])
    except Exception as e:
        res = {"ok": False, "message": f"shazamio: {str(e)[:180]}"}
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
