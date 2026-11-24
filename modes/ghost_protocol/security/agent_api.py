"""API SECURITY AGENT : decouverte des endpoints reels (code client, documentation OpenAPI), controle d'acces SANS authentification,
methodes annoncees, gestion d'erreur. Lecture seule : aucune connexion, aucun jeton, aucune ecriture."""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode

from modes.ghost_protocol.security.agent_web import SIG_TRACE
from modes.ghost_protocol.security.modele import Gravite, Preuve, Resultat, Statut, masquer

RX_SENSIBLE = re.compile(r"user|admin|account|basket|order|payment|card|address|config|secret|token|key|credential|feedback|complaint|"
                         r"memor|whoami|application-configuration|debug|internal|password|wallet|delivery", re.I)
DOCS = ("/api-docs", "/api-docs/swagger.json", "/swagger.json", "/openapi.json", "/v2/api-docs", "/v3/api-docs")


def _res(ctx, **kw):
    return ctx.ajouter(Resultat(agent="API", **kw))


def _endpoints_openapi(texte: str) -> set:
    try:
        d = json.loads(texte)
    except ValueError:
        return set()
    if not isinstance(d, dict) or not ("paths" in d):
        return set()
    base = (d.get("basePath") or "").rstrip("/")
    out = set()
    for chemin, ops in (d.get("paths") or {}).items():
        if isinstance(ops, dict) and "get" in {k.lower() for k in ops}:
            out.add(base + chemin)
    return out


def decouvrir(ctx) -> set:
    base = ctx.cible.url_base()
    eps = set(ctx.carto.endpoints) if ctx.carto else set()
    docs_trouvees = []
    for d in DOCS:
        ctx.verifier_arret()
        r = ctx.client.request("GET", base + d, suivre=False, categorie="api", detail=f"documentation API {d}")
        if r.ok and r.statut == 200 and "json" in r.entetes.get("content-type", ""):
            spec = _endpoints_openapi(r.texte)
            if spec:
                docs_trouvees.append(d)
                eps |= spec
    ctx.faits["docs_api"] = docs_trouvees
    if docs_trouvees:
        ctx.observer(f"Spécification OpenAPI lisible : {', '.join(docs_trouvees)}")
    ctx.faits["endpoints_api"] = len(eps)
    return {e for e in eps if "{" not in e and ":" not in e and "${" not in e}


def analyser(ctx, maxi: int = 30):
    if not ctx.faits.get("joignable", False):
        ctx.limiter("analyse API non effectuée : cible injoignable")
        return
    base = ctx.cible.url_base()
    eps = sorted(decouvrir(ctx))[:maxi]
    if not eps:
        ctx.limiter("Aucun endpoint d'API découvert : analyse API limitée (la découverte se base sur le code client et la documentation OpenAPI).")
        return
    proteges = ouverts = 0
    for ep in eps:
        ctx.verifier_arret()
        r = ctx.client.request("GET", base + ep, suivre=False, categorie="api", detail=f"endpoint {ep}")
        if not r.ok:
            continue
        if r.statut in (401, 403):
            proteges += 1
            if r.entetes.get("www-authenticate"):
                ctx.observer(f"Authentification annoncée par {ep} : {r.entetes['www-authenticate'][:60]}")
            continue
        if r.statut >= 500:
            _res(ctx, categorie="erreur-serveur", titre=f"Erreur serveur non gérée sur {ep}", description=f"GET {ep} répond HTTP {r.statut}.",
                 gravite=Gravite.FAIBLE, composant="API", ressource=base + ep, methode="requête GET sans paramètre", confiance=0.5,
                 impact="Robustesse insuffisante ; peut révéler des détails internes.", recommandation="Valider les entrées ; gérer les erreurs de façon générique.",
                 references=["CWE-755"], cle_validation="api_500", donnees={"url": base + ep},
                 preuves=[Preuve(f"GET {ep}", r.statut, masquer(r.texte[:150]))])
            continue
        if r.statut == 200 and "json" in r.entetes.get("content-type", ""):
            ouverts += 1
            if RX_SENSIBLE.search(ep) and len(r.corps) > 2:
                _res(ctx, categorie="controle-acces", titre=f"Ressource d'API sensible lisible sans authentification : {ep}",
                     description=f"GET {ep} renvoie des données JSON sans aucune authentification.", gravite=Gravite.MOYENNE,
                     composant="API", ressource=base + ep, methode="requête GET non authentifiée", confiance=0.45, statut=Statut.A_VERIFIER,
                     impact="Exposition de données potentiellement sensibles à tout visiteur.",
                     recommandation="Exiger une authentification et un contrôle d'autorisation par objet.", references=["CWE-306", "CWE-862"],
                     cle_validation="api_non_auth", donnees={"url": base + ep, "ep": ep},
                     preuves=[Preuve(f"GET {ep}", r.statut, masquer(r.texte[:200]), [f"taille {len(r.corps)} octets"])])
    ctx.faits.update(api_testes=len(eps), api_proteges=proteges, api_ouverts=ouverts)
    ctx.observer(f"API : {len(eps)} endpoints GET testés sans authentification — {proteges} protégés (401/403), {ouverts} répondent en JSON.")
    # methodes annoncees (OPTIONS) sur quelques endpoints
    for ep in eps[:10]:
        ctx.verifier_arret()
        r = ctx.client.request("OPTIONS", base + ep, suivre=False, categorie="api", detail=f"OPTIONS {ep}")
        allow = (r.entetes.get("allow") or r.entetes.get("access-control-allow-methods") or "") if r.ok else ""
        risque = sorted({m.strip().upper() for m in allow.split(",") if m.strip().upper() in ("PUT", "DELETE", "PATCH", "TRACE")})
        if risque:
            _res(ctx, categorie="methodes-http", titre=f"Méthodes à risque annoncées sur {ep}", description=f"Allow/CORS : {allow[:100]}",
                 gravite=Gravite.INFO, composant="API", ressource=base + ep, methode="requête OPTIONS", confiance=0.4, statut=Statut.A_VERIFIER,
                 impact="Des écritures non authentifiées pourraient être possibles (non testé : l'audit n'écrit jamais).",
                 recommandation="Restreindre les méthodes et exiger l'authentification.", references=["CWE-650"],
                 cle_validation="api_options", donnees={"url": base + ep, "methodes": risque})
    ctx.limiter("L'analyse API n'effectue aucune connexion ni écriture : contrôle d'accès authentifié, IDOR, JWT et mass-assignment NON testés.")
