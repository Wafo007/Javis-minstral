"""Perimetre autorise : registre de cibles, classification des plateformes, garde appliquee a CHAQUE action reseau.

Principes (non negociables) :
  * aucune cible n'est testable sans enregistrement explicite et date (attestation de l'utilisatrice) ;
  * le domaine principal d'une plateforme d'apprentissage n'est JAMAIS une cible, meme enregistre ;
  * hors perimetre, expiration, arret d'urgence, budget depasse, action inconnue ou methode non lecture => refus ;
  * seules les methodes GET / HEAD / OPTIONS existent (aucune ecriture, aucun envoi de formulaire, aucune authentification) ;
  * le LLM n'a aucun moyen d'enregistrer ni d'elargir une cible (aucun outil du registre Jarvis).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

# Plateformes d'apprentissage : hotes qui ne sont PAS des cibles. Les machines/labs s'enregistrent par leur adresse propre.
PLATEFORMES = {
    "tryhackme.com": "TryHackMe", "hackthebox.com": "Hack The Box", "portswigger.net": "PortSwigger",
    "pentesterlab.com": "PentesterLab", "owasp.org": "OWASP", "owasp-juice.shop": "OWASP Juice Shop (site du projet)",
}
SOUS_DOMAINES_PLATEFORME = {"www", "app", "login", "academy", "portal", "account", "accounts", "blog", "docs", "support", "api", "labs"}
SUFFIXE_LAB_PORTSWIGGER = ".web-security-academy.net"          # instances de labs demarrees par l'utilisatrice

ACTIONS_PERMISES = {"http_get", "http_head", "http_options", "tcp_connect", "tls_handshake", "analyse_statique",
                    "outil_externe", "osv_lookup"}
METHODES_PERMISES = {"GET", "HEAD", "OPTIONS"}
DUREE_MAX_H = 24 * 30


class RefusPerimetre(Exception):
    """Action refusee par la garde (hors perimetre, expiree, arret d'urgence, budget...)."""


@dataclass
class Classification:
    type: str                 # local | reseau_prive | lab_portswigger | externe | plateforme | code_local | invalide
    hote: str = ""
    port: int | None = None
    schema: str = "http"
    plateforme: str = ""
    bloque: bool = False
    raison: str = ""


def _analyser(brut: str):
    t = str(brut or "").strip()
    if not t:
        return None
    if "://" not in t:
        t = "http://" + t
    try:
        u = urlsplit(t)
        hote = (u.hostname or "").lower().rstrip(".")
        port = u.port or (443 if u.scheme == "https" else 80)
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not hote:
        return None
    return u.scheme, hote, port


def classer(brut: str) -> Classification:
    p = _analyser(brut)
    if not p:
        return Classification("invalide", raison="adresse illisible (attendu : http(s)://hote[:port] ou IP)", bloque=True)
    schema, hote, port = p
    for racine, nom in PLATEFORMES.items():
        if hote == racine or (hote.endswith("." + racine) and hote[: -len(racine) - 1].split(".")[-1] in SOUS_DOMAINES_PLATEFORME):
            return Classification("plateforme", hote, port, schema, nom, True,
                                  f"{hote} est le site de la plateforme {nom}, pas un laboratoire : jamais testable. "
                                  "Enregistrez l'adresse de VOTRE machine/laboratoire (IP du VPN ou URL d'instance).")
    if hote.endswith(SUFFIXE_LAB_PORTSWIGGER):
        return Classification("lab_portswigger", hote, port, schema, "PortSwigger Web Security Academy")
    if hote == "localhost":
        return Classification("local", hote, port, schema, "application locale")
    try:
        ip = ipaddress.ip_address(hote)
    except ValueError:
        return Classification("externe", hote, port, schema, "hote externe")
    if ip.is_loopback:
        return Classification("local", hote, port, schema, "application locale")
    if ip.is_private or ip.is_link_local:
        return Classification("reseau_prive", hote, port, schema, "machine de reseau prive / VPN de laboratoire")
    return Classification("externe", hote, port, schema, "adresse IP publique")


@dataclass
class Cible:
    id: str
    hote: str
    ports: list
    schema: str
    type: str
    plateforme: str
    attestation: str
    cree_le: float
    expire_le: float
    ips: list = field(default_factory=list)
    actions: list = field(default_factory=lambda: ["web", "api", "reseau", "outils"])
    tls_verifier: bool = True
    revoquee: bool = False
    chemin_code: str = ""            # pour les cibles de type code_local

    def valide(self, maintenant=None) -> tuple[bool, str]:
        t = maintenant if maintenant is not None else time.time()
        if self.revoquee:
            return False, "cible revoquee"
        if t > self.expire_le:
            return False, "autorisation expiree"
        return True, ""

    def url_base(self) -> str:
        port = self.ports[0] if self.ports else (443 if self.schema == "https" else 80)
        defaut = 443 if self.schema == "https" else 80
        return f"{self.schema}://{self.hote}" + ("" if port == defaut else f":{port}")


def resoudre(hote: str) -> list:
    try:
        return sorted({i[4][0] for i in socket.getaddrinfo(hote, None)})
    except OSError:
        return []


class Registre:
    """Registre persistant (JSON) des cibles autorisees. Ecriture atomique, verrouille."""

    def __init__(self, fichier: Path, resolveur=resoudre, horloge=time.time):
        self.fichier = Path(fichier)
        self._verrou = threading.RLock()
        self._resoudre = resolveur
        self._horloge = horloge

    def _lire(self) -> list:
        try:
            return [Cible(**d) for d in json.loads(self.fichier.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            return []

    def _ecrire(self, cibles: list):
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.fichier.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(c) for c in cibles], ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.fichier)

    def lister(self, actives_seulement=False) -> list:
        with self._verrou:
            c = self._lire()
            return [x for x in c if x.valide(self._horloge())[0]] if actives_seulement else c

    def enregistrer(self, url: str, attestation: str = "", duree_h: float = 24, ports=None, actions=None,
                    proprietaire_confirme: bool = False, tls_verifier: bool = True) -> Cible:
        cl = classer(url)
        if cl.bloque:
            raise RefusPerimetre(cl.raison)
        att = (attestation or "").strip()
        if cl.type in ("reseau_prive", "lab_portswigger") and len(att) < 15:
            raise RefusPerimetre("attestation requise (>= 15 caracteres) : decrivez le laboratoire/la machine et que vous l'avez demarre.")
        if cl.type == "externe":
            if not proprietaire_confirme or len(att) < 40:
                raise RefusPerimetre("hote externe : autorisation ecrite du proprietaire requise (attestation >= 40 caracteres ET "
                                     "confirmation explicite). En cas de doute, ne testez pas.")
        if cl.type == "local" and not att:
            att = "Application locale lancee par l'utilisatrice sur sa propre machine."
        duree_h = max(0.1, min(float(duree_h), DUREE_MAX_H))
        ips = [cl.hote] if _est_ip(cl.hote) else self._resoudre(cl.hote)
        if not ips:
            raise RefusPerimetre(f"impossible de resoudre {cl.hote} : cible non enregistree.")
        if cl.type == "externe" and any(_ip_non_publique_ou_ambigue(i) for i in ips) and not _est_ip(cl.hote):
            raise RefusPerimetre("le nom pointe vers une adresse locale/privee : enregistrez-le comme laboratoire local/prive.")
        ports = sorted({int(p) for p in (ports or [cl.port])})
        now = self._horloge()
        cid = "T-" + hashlib.sha1(f"{cl.hote}:{ports}:{now}".encode()).hexdigest()[:8].upper()
        cible = Cible(cid, cl.hote, ports, cl.schema, cl.type, cl.plateforme, att, now, now + duree_h * 3600, ips,
                      list(actions or ["web", "api", "reseau", "outils"]), tls_verifier)
        with self._verrou:
            cibles = [c for c in self._lire() if not (c.hote == cible.hote and c.ports == cible.ports and not c.revoquee)]
            cibles.append(cible)
            self._ecrire(cibles)
        return cible

    def enregistrer_code(self, chemin: str, attestation: str = "", duree_h: float = 24) -> Cible:
        p = Path(chemin).expanduser().resolve()
        if not p.is_dir():
            raise RefusPerimetre(f"dossier introuvable : {chemin}")
        if p == Path(p.anchor) or len(p.parts) < 3:
            raise RefusPerimetre("dossier trop large (racine) : choisissez le dossier du projet a auditer.")
        att = (attestation or "").strip() or "Code source appartenant a l'utilisatrice (analyse statique locale)."
        now = self._horloge()
        cible = Cible("C-" + hashlib.sha1(f"{p}:{now}".encode()).hexdigest()[:8].upper(), "code_local", [], "file", "code_local",
                      "code local", att, now, now + min(duree_h, DUREE_MAX_H) * 3600, ["127.0.0.1"], ["code"], True, False, str(p))
        with self._verrou:
            cibles = [c for c in self._lire() if not (c.type == "code_local" and c.chemin_code == str(p) and not c.revoquee)]
            cibles.append(cible)
            self._ecrire(cibles)
        return cible

    def revoquer(self, identifiant_ou_hote: str) -> int:
        n = 0
        with self._verrou:
            cibles = self._lire()
            for c in cibles:
                if not c.revoquee and identifiant_ou_hote in (c.id, c.hote):
                    c.revoquee, n = True, n + 1
            self._ecrire(cibles)
        return n

    def trouver(self, url: str):
        """(Cible|None, raison) pour une URL/hote : cible active correspondant EXACTEMENT a l'hote et au port."""
        cl = classer(url)
        if cl.bloque:
            return None, cl.raison
        raison = "cible non enregistree : aucun test (demandez l'autorisation via le HUD ou scripts/security_cible.py)"
        for c in self.lister():
            if c.hote == cl.hote and (cl.port in c.ports):
                ok, r = c.valide(self._horloge())
                if ok:
                    return c, ""
                raison = r
        return None, raison


def _est_ip(h: str) -> bool:
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def _ip_non_publique_ou_ambigue(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
        return a.is_private or a.is_loopback or a.is_link_local or a.is_reserved
    except ValueError:
        return True


class Garde:
    """Autorise (ou refuse) chaque action d'un audit. Un seul point de controle, journalise."""

    def __init__(self, cible: Cible, journal, arret, rps_max: float = 8.0, budget_requetes: int = 800,
                 resolveur=resoudre, horloge=time.time, dormir=None):
        self.cible, self.journal, self.arret = cible, journal, arret
        self.intervalle = 1.0 / max(0.1, rps_max)
        self.budget = budget_requetes
        self.compte = 0
        self._resoudre = resolveur
        self._horloge = horloge
        self._dernier = 0.0
        self._verrou = threading.Lock()
        self._cache_dns: dict = {}
        self._dormir = dormir or (lambda s: arret.attendre(s))
        self.refus = 0

    def _refuser(self, action, detail, raison):
        self.refus += 1
        self.journal.ecrire("REFUS", action=action, detail=detail, raison=raison)
        raise RefusPerimetre(raison)

    def autoriser(self, action: str, hote: str, port: int | None = None, methode: str = "", detail: str = "", categorie: str = "",
                  rps: float | None = None):
        intervalle = (1.0 / rps) if rps else self.intervalle
        if self.arret.actif():
            self._refuser(action, detail, "arret d'urgence actif")
        ok, r = self.cible.valide(self._horloge())
        if not ok:
            self._refuser(action, detail, r)
        if action not in ACTIONS_PERMISES:
            self._refuser(action, detail, f"action non permise : {action}")
        if action.startswith("http_") and methode.upper() not in METHODES_PERMISES:
            self._refuser(action, detail, f"methode {methode} interdite (lecture seule)")
        if categorie and categorie not in self.cible.actions:
            self._refuser(action, detail, f"categorie '{categorie}' non autorisee pour cette cible")
        if action != "osv_lookup" and action != "analyse_statique":
            if (hote or "").lower().rstrip(".") != self.cible.hote:
                self._refuser(action, detail, f"HORS PERIMETRE : {hote} n'est pas {self.cible.hote}")
            if port is not None and port not in self.cible.ports and action.startswith(("http_", "tls_")):
                self._refuser(action, detail, f"HORS PERIMETRE : port {port} non autorise")
            if not _est_ip(self.cible.hote):                    # anti DNS-rebinding : les IP doivent rester celles enregistrees
                maintenant = self._horloge()
                ts, ips = self._cache_dns.get(hote, (0, None))
                if ips is None or maintenant - ts > 60:
                    ips = self._resoudre(hote)
                    self._cache_dns[hote] = (maintenant, ips)
                if not ips or not set(ips) <= set(self.cible.ips):
                    self._refuser(action, detail, "l'adresse IP de l'hote a change depuis l'enregistrement (rebinding ?)")
        with self._verrou:
            if self.compte >= self.budget:
                self._refuser(action, detail, f"budget de requetes atteint ({self.budget})")
            self.compte += 1
            attente = self._dernier + intervalle - self._horloge()
            self._dernier = max(self._horloge(), self._dernier + intervalle) if attente > 0 else self._horloge()
        if attente > 0 and self._dormir(attente):
            self._refuser(action, detail, "arret d'urgence actif")
        self.journal.ecrire("ACTION", action=action, methode=methode, hote=hote, port=port, detail=detail)
