"""RECON AGENT : cartographie reelle (pages, formulaires, scripts, endpoints, technologies) par requetes GET dans le perimetre."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urljoin, urlsplit

from modes.ghost_protocol.security.contexte import AuditInterrompu

STATIQUES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".css", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".webp", ".map", ".pdf", ".zip")
RX_ENDPOINT_JS = re.compile(r"""["'`](/(?:rest|api|b2b|graphql|v\d+|socket\.io)(?:/[A-Za-z0-9_\-\.]+)*/?)["'`?]""")
RX_VERSIONS_JS = re.compile(r"(jquery|angular|react|vue|bootstrap|lodash|moment)[-.@/]*v?(\d+\.\d+(?:\.\d+)?)", re.I)


@dataclass
class Cartographie:
    base: str
    pages: dict = field(default_factory=dict)            # url -> {"statut", "titre", "type"}
    formulaires: list = field(default_factory=list)      # {"page","action","methode","champs":[{"nom","type"}]}
    scripts: list = field(default_factory=list)
    endpoints: set = field(default_factory=set)          # chemins (sans domaine)
    technologies: dict = field(default_factory=dict)     # nom -> preuve
    params: list = field(default_factory=list)           # (url, nom_parametre)
    entetes: dict = field(default_factory=dict)          # url -> entetes de la reponse
    cookies: list = field(default_factory=list)          # (url, ligne Set-Cookie)
    robots: list = field(default_factory=list)           # chemins Disallow

    def vers_dict(self) -> dict:
        return {"base": self.base, "pages": self.pages, "formulaires": self.formulaires, "scripts": self.scripts,
                "endpoints": sorted(self.endpoints), "technologies": self.technologies, "params": [list(p) for p in self.params],
                "robots": self.robots}


class _Analyseur(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.liens, self.scripts, self.formulaires, self.meta, self.titre = [], [], [], {}, ""
        self._form, self._in_title = None, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.liens.append(a["href"])
        elif tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        elif tag == "meta" and a.get("name"):
            self.meta[a["name"].lower()] = a.get("content", "")
        elif tag == "title":
            self._in_title = True
        elif tag == "form":
            self._form = {"action": a.get("action", ""), "methode": (a.get("method") or "get").upper(), "champs": []}
            self.formulaires.append(self._form)
        elif tag in ("input", "textarea", "select") and self._form is not None:
            self._form["champs"].append({"nom": a.get("name", ""), "type": (a.get("type") or tag).lower()})

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.titre += data.strip()


def _origine(u: str):
    p = urlsplit(u)
    return (p.hostname or "").lower(), p.port or (443 if p.scheme == "https" else 80)


def _meme_origine(url: str, base: str) -> bool:
    return _origine(url) == _origine(base)


def reconnaitre(ctx, max_pages: int = 25, profondeur: int = 2, max_scripts: int = 8) -> Cartographie:
    base = ctx.cible.url_base()
    carto = Cartographie(base)
    ctx.carto = carto
    racine = ctx.client.request("GET", base + "/", categorie="web", detail="recon : page d'accueil")
    if not racine.ok:
        ctx.faits["joignable"] = False
        ctx.limiter(f"cible injoignable ({racine.erreur or racine.statut})")
        return carto
    ctx.faits["joignable"] = True
    _noter(ctx, carto, base + "/", racine)
    file_attente = [(base + "/", 0)]
    vus = {base + "/"}
    while file_attente and len(carto.pages) < max_pages:
        ctx.verifier_arret()
        url, niveau = file_attente.pop(0)
        rep = racine if url == base + "/" else ctx.client.request("GET", url, categorie="web", detail="recon : exploration")
        if not rep.ok:
            continue
        if url != base + "/":
            _noter(ctx, carto, url, rep)
        if "html" not in rep.entetes.get("content-type", "") or niveau >= profondeur:
            continue
        an = _Analyseur()
        try:
            an.feed(rep.texte)
        except Exception:
            continue
        for f in an.formulaires:
            f["page"] = url
            f["action"] = urljoin(url, f["action"] or url)
            carto.formulaires.append(f)
            if f["methode"] == "GET":
                carto.params += [(f["action"], c["nom"]) for c in f["champs"] if c["nom"]]
        for src in an.scripts:
            u = urljoin(url, src)
            if _meme_origine(u, base) and u not in carto.scripts:
                carto.scripts.append(u)
        for lien in an.liens:
            u = urljoin(url, lien).split("#")[0]
            if not _meme_origine(u, base) or u in vus or urlsplit(u).path.lower().endswith(STATIQUES) or not u.startswith("http"):
                continue
            vus.add(u)
            for nom, _ in parse_qsl(urlsplit(u).query):
                carto.params.append((u.split("?")[0], nom))
            file_attente.append((u, niveau + 1))
        for nom, val in an.meta.items():
            if nom == "generator" and val:
                carto.technologies[val] = "balise meta generator"
    # robots.txt et scripts : endpoints reels cites par le code client
    rob = ctx.client.request("GET", base + "/robots.txt", categorie="web", detail="recon : robots.txt")
    if rob.ok and rob.statut == 200 and "html" not in rob.entetes.get("content-type", "") and "disallow" in rob.texte.lower():
        carto.robots = [l.split(":", 1)[1].strip() for l in rob.texte.splitlines() if l.lower().startswith("disallow:") and l.split(":", 1)[1].strip()][:30]
    for src in carto.scripts[:max_scripts]:
        ctx.verifier_arret()
        js = ctx.client.request("GET", src, categorie="web", detail="recon : analyse d'un script")
        if not js.ok or js.statut != 200:
            continue
        for m in RX_ENDPOINT_JS.finditer(js.texte[:MAX_JS]):
            chemin = m.group(1)
            if "${" not in chemin and len(chemin) < 120:
                carto.endpoints.add(chemin.rstrip("/") or "/")
        for m in RX_VERSIONS_JS.finditer(js.texte[:MAX_JS]):
            carto.technologies.setdefault(f"{m.group(1).lower()} {m.group(2)}", f"script {src.rsplit('/', 1)[-1]}")
    ctx.faits.update(pages=len(carto.pages), formulaires=len(carto.formulaires), endpoints=len(carto.endpoints),
                     scripts=len(carto.scripts), a_api=any(e.startswith(("/api", "/rest")) for e in carto.endpoints))
    for t, p in sorted(carto.technologies.items()):
        ctx.observer(f"Technologie : {t} ({p})")
    return carto


MAX_JS = 600_000


def _noter(ctx, carto, url, rep):
    carto.pages[url] = {"statut": rep.statut, "type": rep.entetes.get("content-type", "").split(";")[0], "titre": ""}
    carto.entetes[url] = rep.entetes
    for c in rep.cookies:
        carto.cookies.append((url, c))
    for h in ("server", "x-powered-by", "via", "x-aspnet-version", "x-generator"):
        if rep.entetes.get(h):
            carto.technologies[f"{h}: {rep.entetes[h]}"] = f"en-tete {h}"
    if "html" in rep.entetes.get("content-type", ""):
        an = _Analyseur()
        try:
            an.feed(rep.texte[:200000])
            carto.pages[url]["titre"] = an.titre[:120]
        except Exception:
            pass
        m = re.search(r'ng-version="([\d.]+)"', rep.texte)
        if m:
            carto.technologies[f"angular {m.group(1)}"] = "attribut ng-version"
