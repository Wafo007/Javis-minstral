"""Connexion Spotify (à faire UNE fois) — récupère un refresh_token réutilisable.

    python scripts/spotify_login.py

Prérequis (voir docs/spotify.md) : crée une app sur
https://developer.spotify.com/dashboard , note client_id / client_secret, et ajoute
l'URI de redirection EXACTE : http://127.0.0.1:8899/callback . Mets client_id et
client_secret dans config.yaml (section spotify). Ce script ouvre ton navigateur,
tu autorises, et il sauve le refresh_token dans logs/spotify/token.json (gitignoré).
"""
import base64
import json
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
import requests  # noqa: E402

from core.config import reglage  # noqa: E402

for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PORT = 8899
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
SCOPES = ("playlist-modify-private playlist-modify-public playlist-read-private "
          "user-read-email user-read-private user-read-playback-state "
          "user-modify-playback-state")
_CODE = {}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        q = urllib.parse.urlparse(self.path)
        if q.path != "/callback":
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(q.query)
        _CODE["code"] = (params.get("code") or [None])[0]
        _CODE["error"] = (params.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<h2>Spotify connecté — tu peux fermer cet onglet.</h2>"
                         .encode("utf-8"))


def _dossier():
    d = RACINE / (reglage("spotify.dossier", "logs/spotify"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def main():
    cid = reglage("spotify.client_id", "")
    secret = reglage("spotify.client_secret", "")
    if not (cid and secret):
        print("Renseigne d'abord spotify.client_id / spotify.client_secret dans "
              "config.yaml (voir docs/spotify.md).")
        return

    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": REDIRECT,
        "scope": SCOPES,
        "show_dialog": "true"})   # force le ré-consentement (sinon scopes d'une auth précédente)
    print("\nOuvre cette adresse et autorise (elle devrait s'ouvrir seule) :\n ", url)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    serveur = HTTPServer(("127.0.0.1", PORT), _Handler)
    print(f"En attente de l'autorisation sur {REDIRECT} … (Ctrl+C pour annuler)")
    while "code" not in _CODE and "error" not in _CODE:
        serveur.handle_request()

    if _CODE.get("error") or not _CODE.get("code"):
        print("\n❌ Autorisation refusée ou annulée :", _CODE.get("error"))
        return

    # Échange du code contre les tokens (Basic auth client_id:client_secret).
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    r = requests.post("https://accounts.spotify.com/api/token", data={
        "grant_type": "authorization_code", "code": _CODE["code"],
        "redirect_uri": REDIRECT}, headers={"Authorization": f"Basic {auth}"},
        timeout=15)
    if r.status_code != 200:
        print("\n❌ Échange du code échoué :", r.status_code, r.text[:200])
        return
    data = r.json()
    (_dossier() / "token.json").write_text(json.dumps({
        "refresh_token": data.get("refresh_token")}), encoding="utf-8")
    scopes = data.get("scope", "")
    print("\n✅ Spotify connecté, refresh_token sauvegardé dans", _dossier())
    print("   Permissions accordées :", scopes or "(aucune ?!)")
    if "playlist-modify" not in scopes:
        print("   ⚠️ Le droit d'écriture des playlists (playlist-modify) N'EST PAS "
              "accordé — l'ajout échouera (403). Refais l'autorisation en cliquant "
              "bien « Agree » sur l'écran qui liste les permissions.")
    if "user-modify-playback-state" not in scopes:
        print("   ⚠️ Le contrôle de lecture n'est pas accordé. Les titres pourront "
              "être ouverts, mais pas lancés automatiquement.")
    print("   Redémarre Jarvis. Tu peux ensuite dire « lance ma playlist Chill » "
          "ou « ajoute-la à ma playlist ».")


if __name__ == "__main__":
    main()
