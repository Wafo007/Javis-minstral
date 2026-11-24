"""Client HTTP « encadre » : toute requete passe par la Garde (perimetre, debit, budget, arret d'urgence).

Lecture seule (GET/HEAD/OPTIONS), redirections suivies a la main (chaque saut est re-valide), corps plafonne, aucun cookie
conserve, aucune authentification, aucun envoi de formulaire. Le transport est injectable (tests sans reseau).
"""
from __future__ import annotations

import http.client
import socket
import ssl
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from modes.ghost_protocol.security.perimetre import RefusPerimetre

UA = "JarvisSecurityAudit/1.0 (laboratoire autorise; lecture seule)"
MAX_CORPS = 512 * 1024


@dataclass
class Reponse:
    url: str
    statut: int = 0
    entetes: dict = field(default_factory=dict)      # nom en minuscules -> derniere valeur
    cookies: list = field(default_factory=list)      # lignes Set-Cookie brutes
    corps: bytes = b""
    duree: float = 0.0
    erreur: str = ""
    redirections: list = field(default_factory=list)

    @property
    def texte(self) -> str:
        return self.corps.decode("utf-8", "replace")

    @property
    def ok(self) -> bool:
        return not self.erreur and self.statut > 0


def transport_http(methode, url, entetes, timeout, verifier_tls=True):
    """(statut, [(nom, valeur)], corps). Ne suit PAS les redirections ; ne lit jamais plus de MAX_CORPS."""
    u = urlsplit(url)
    port = u.port or (443 if u.scheme == "https" else 80)
    chemin = (u.path or "/") + ("?" + u.query if u.query else "")
    if u.scheme == "https":
        ctx = ssl.create_default_context()
        if not verifier_tls:
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        conn = http.client.HTTPSConnection(u.hostname, port, timeout=timeout, context=ctx)
    else:
        conn = http.client.HTTPConnection(u.hostname, port, timeout=timeout)
    try:
        conn.request(methode, chemin, headers=entetes)
        r = conn.getresponse()
        corps = b"" if methode == "HEAD" else r.read(MAX_CORPS)
        return r.status, r.getheaders(), corps
    finally:
        conn.close()


class ClientCadre:
    def __init__(self, garde, transport=None, timeout: float = 8.0, categorie: str = ""):
        self.garde = garde
        self.transport = transport or (lambda m, u, h, t: transport_http(m, u, h, t, garde.cible.tls_verifier))
        self.timeout = timeout
        self.categorie = categorie
        self.requetes = 0
        self.erreurs_consecutives = 0

    def request(self, *a, **k) -> Reponse:
        """Alias anglais utilise par les agents."""
        return self.requete(*a, **k)

    def requete(self, methode: str, url: str, entetes: dict | None = None, suivre: bool = True, detail: str = "",
                categorie: str = "") -> Reponse:
        methode = methode.upper()
        h = {"User-Agent": UA, "Accept": "*/*", "Connection": "close"}
        h.update(entetes or {})
        courant, sauts = url, []
        debut = time.time()
        for _ in range(6):
            u = urlsplit(courant)
            port = u.port or (443 if u.scheme == "https" else 80)
            try:
                self.garde.autoriser("http_" + methode.lower(), u.hostname or "", port, methode, detail or courant, categorie or self.categorie)
            except RefusPerimetre as e:
                if sauts and not self.garde.arret.actif():      # redirection vers l'exterieur : on s'arrete sans la suivre, l'etape continue
                    return Reponse(courant, erreur=f"redirection hors périmètre refusée : {e}", duree=time.time() - debut, redirections=sauts)
                raise
            try:
                statut, entetes_rep, corps = self.transport(methode, courant, h, self.timeout)
            except RefusPerimetre:
                raise
            except (socket.timeout, TimeoutError):
                self.erreurs_consecutives += 1
                return Reponse(courant, erreur="timeout", duree=time.time() - debut, redirections=sauts)
            except (OSError, http.client.HTTPException, ssl.SSLError) as e:
                self.erreurs_consecutives += 1
                return Reponse(courant, erreur=f"{type(e).__name__}: {str(e)[:120]}", duree=time.time() - debut, redirections=sauts)
            self.requetes += 1
            self.erreurs_consecutives = 0
            d = {}
            cookies = []
            for n, v in entetes_rep:
                if n.lower() == "set-cookie":
                    cookies.append(v)
                d[n.lower()] = v
            rep = Reponse(courant, statut, d, cookies, corps[:MAX_CORPS], time.time() - debut, redirections=sauts)
            if suivre and statut in (301, 302, 303, 307, 308) and d.get("location"):
                sauts.append(courant)
                courant = urljoin(courant, d["location"])          # le saut suivant sera re-valide par la garde
                continue
            return rep
        return Reponse(courant, erreur="trop de redirections", redirections=sauts)
