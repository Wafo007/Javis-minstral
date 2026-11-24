"""WEB SECURITY AGENT : verifications non destructives (lecture seule) -- en-tetes, cookies, CORS, chemins exposes avec
detection des faux positifs (reference « page inexistante »), formulaires, reflexion d'entree, erreurs SQL (sonde differentielle).
Chaque detection cree un Resultat POTENTIEL/A_VERIFIER avec une cle de validation ; c'est l'agent de validation qui promeut."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from urllib.parse import urlencode, urlsplit

from modes.ghost_protocol.security.modele import Gravite, Preuve, Resultat, Statut, masquer

SIG_SQL = re.compile(r"(SQLITE_ERROR|SQLite3::|SQLSTATE\[|syntax error at or near|You have an error in your SQL syntax|"
                     r"ORA-\d{5}|Unclosed quotation mark|mysql_fetch|pg_query\(|PSQLException|SequelizeDatabaseError|near \"[^\"]*\": syntax error)", re.I)
SIG_TRACE = re.compile(r"(Traceback \(most recent call last\)|\bat [\w.$<>]+ \([^)]*\.js:\d+:\d+\)|java\.lang\.\w+Exception|"
                       r"Fatal error:.*on line \d+|Microsoft OLE DB|stack trace:)", re.I)


def empreinte_corps(rep) -> tuple:
    texte = re.sub(r"\s+", " ", rep.texte[:4000])
    ct = str(rep.entetes.get("content-type", "")).split(";")[0].strip().lower()
    return rep.statut, len(rep.corps), hashlib.sha1(texte.encode("utf-8", "replace")).hexdigest()[:12], ct


def reference_inexistante(ctx) -> list:
    """Reponses a 2 chemins qui n'existent pas : permettent de reconnaitre un « catch-all » (SPA renvoyant 200 partout)."""
    refs = []
    for _ in range(2):
        r = ctx.client.request("GET", f"{ctx.cible.url_base()}/jsi-inexistant-{secrets.token_hex(5)}", categorie="web", detail="reference 404")
        if r.ok:
            refs.append(empreinte_corps(r))
    ctx.faits["reference_404"] = refs
    return refs


def ressemble_a_reference(rep, refs) -> bool:
    if not refs:
        return False
    statut, taille, h, ct = empreinte_corps(rep)
    # taille proche seulement si le type de contenu est le meme : un texte brut de 110 octets n'est pas l'index HTML de 118 octets
    return any(statut == r[0] and (h == r[2] or (ct == (r[3] if len(r) > 3 else ct) and abs(taille - r[1]) <= max(40, 0.02 * r[1]))) for r in refs)


def _res(ctx, **kw) -> Resultat:
    return ctx.ajouter(Resultat(agent="WEB", **kw))


# ---------------------------------------------------------------- en-tetes
def _en_tetes(ctx, carto):
    base = ctx.cible.url_base() + "/"
    h = carto.entetes.get(base) or next(iter(carto.entetes.values()), {})
    https = ctx.cible.schema == "https"
    regles = [
        ("content-security-policy", "En-tête Content-Security-Policy absent", Gravite.MOYENNE, "CWE-693",
         "Aucune politique CSP : une injection de script (XSS) n'est pas limitée par le navigateur.",
         "Définir une CSP stricte (default-src 'self', pas de 'unsafe-inline')."),
        ("x-content-type-options", "En-tête X-Content-Type-Options absent", Gravite.FAIBLE, "CWE-693",
         "Le navigateur peut deviner le type MIME (MIME sniffing).", "Ajouter X-Content-Type-Options: nosniff."),
        ("referrer-policy", "En-tête Referrer-Policy absent", Gravite.INFO, "CWE-200",
         "L'URL complète peut fuiter dans l'en-tête Referer vers des sites tiers.", "Ajouter Referrer-Policy: strict-origin-when-cross-origin."),
        ("permissions-policy", "En-tête Permissions-Policy absent", Gravite.INFO, "CWE-693",
         "Les API sensibles du navigateur ne sont pas restreintes.", "Définir une Permissions-Policy minimale."),
    ]
    for nom, titre, grav, cwe, impact, reco in regles:
        if nom not in h:
            _res(ctx, categorie="en-tetes-securite", titre=titre, description=f"La réponse de {base} ne contient pas l'en-tête {nom}.",
                 gravite=grav, composant="serveur web", ressource=base, methode="analyse des en-têtes HTTP (GET /)", confiance=0.95,
                 impact=impact, recommandation=reco, references=[cwe], cle_validation="entete_absent",
                 donnees={"url": base, "entete": nom},
                 preuves=[Preuve("GET /", 200, f"en-tête '{nom}' absent de la réponse", [f"en-têtes présents : {', '.join(sorted(h))[:200]}"])])
    if "x-frame-options" not in h and "frame-ancestors" not in h.get("content-security-policy", ""):
        _res(ctx, categorie="clickjacking", titre="Protection anti-clickjacking absente",
             description="Ni X-Frame-Options ni CSP frame-ancestors : la page peut être affichée dans une iframe tierce.",
             gravite=Gravite.MOYENNE, composant="serveur web", ressource=base, methode="analyse des en-têtes HTTP (GET /)", confiance=0.9,
             impact="Détournement de clics (clickjacking) sur des actions authentifiées.",
             recommandation="Ajouter X-Frame-Options: DENY ou CSP frame-ancestors 'none'.", references=["CWE-1021"],
             cle_validation="entete_absent", donnees={"url": base, "entete": "x-frame-options", "alt": "frame-ancestors"},
             preuves=[Preuve("GET /", 200, "ni x-frame-options ni frame-ancestors")])
    if https and "strict-transport-security" not in h:
        _res(ctx, categorie="en-tetes-securite", titre="En-tête HSTS absent", description="HTTPS sans Strict-Transport-Security.",
             gravite=Gravite.MOYENNE, composant="serveur web", ressource=base, methode="analyse des en-têtes HTTP", confiance=0.95,
             impact="Rétrogradation vers HTTP possible (SSL stripping).", recommandation="Ajouter Strict-Transport-Security: max-age=31536000; includeSubDomains.",
             references=["CWE-319"], cle_validation="entete_absent", donnees={"url": base, "entete": "strict-transport-security"})
    if not https:
        ctx.observer("La cible est servie en HTTP sans TLS (normal pour un laboratoire local ; à proscrire en production).")
    for nom in ("server", "x-powered-by", "x-aspnet-version"):
        v = h.get(nom, "")
        if v and re.search(r"\d", v):
            _res(ctx, categorie="divulgation-version", titre=f"Version du logiciel divulguée ({nom})", description=f"{nom}: {v}",
                 gravite=Gravite.FAIBLE, composant="serveur web", ressource=base, methode="analyse des en-têtes HTTP", confiance=0.9,
                 impact="Facilite le ciblage de vulnérabilités connues.", recommandation=f"Masquer ou généraliser l'en-tête {nom}.",
                 references=["CWE-200"], cle_validation="entete_present", donnees={"url": base, "entete": nom, "valeur": v},
                 preuves=[Preuve("GET /", 200, f"{nom}: {v}")])


# ---------------------------------------------------------------- cookies
def _cookies(ctx, carto):
    vus = set()
    for url, ligne in carto.cookies:
        nom = ligne.split("=", 1)[0].strip()
        if (url, nom) in vus:
            continue
        vus.add((url, nom))
        bas = ligne.lower()
        manque = [x for x, ok in (("HttpOnly", "httponly" in bas), ("SameSite", "samesite" in bas),
                                  ("Secure", "secure" in bas or ctx.cible.schema != "https")) if not ok]
        if manque:
            _res(ctx, categorie="cookies", titre=f"Cookie « {nom} » sans attribut(s) {', '.join(manque)}",
                 description=f"Le cookie {nom} est émis sans : {', '.join(manque)}.", gravite=Gravite.FAIBLE if "HttpOnly" not in manque else Gravite.MOYENNE,
                 composant="gestion de session", ressource=url, methode="analyse des en-têtes Set-Cookie", confiance=0.9,
                 impact="Vol de session facilité (XSS) ou envoi sur canal non sécurisé.",
                 recommandation="Définir HttpOnly, Secure (HTTPS) et SameSite=Lax/Strict.", references=["CWE-1004", "CWE-614"],
                 cle_validation="cookie_attributs", donnees={"url": url, "cookie": nom, "manque": manque},
                 preuves=[Preuve(f"GET {urlsplit(url).path}", None, masquer(ligne.split(";", 1)[1] if ";" in ligne else "(aucun attribut)"))])


# ---------------------------------------------------------------- CORS
def _cors(ctx):
    base = ctx.cible.url_base() + "/"
    origine = "https://jsi-origine-test.invalid"
    r = ctx.client.request("GET", base, {"Origin": origine}, categorie="web", detail="test CORS")
    if not r.ok:
        return
    acao, cred = r.entetes.get("access-control-allow-origin", ""), r.entetes.get("access-control-allow-credentials", "").lower() == "true"
    if acao == origine or acao == "*":
        grav = Gravite.ELEVEE if (acao == origine and cred) else (Gravite.MOYENNE if acao == origine else Gravite.FAIBLE)
        _res(ctx, categorie="cors", titre="Politique CORS permissive" + (" avec identifiants" if cred else ""),
             description=f"Access-Control-Allow-Origin: {acao}" + (" avec Allow-Credentials: true" if cred else ""), gravite=grav,
             composant="serveur web", ressource=base, methode="requête avec en-tête Origin arbitraire", confiance=0.85,
             impact="Un site tiers peut lire les réponses de l'application" + (" au nom de l'utilisateur connecté." if cred else " (sans identifiants)."),
             recommandation="Restreindre Access-Control-Allow-Origin à une liste blanche d'origines de confiance.", references=["CWE-942"],
             cle_validation="cors", donnees={"url": base, "origine": origine},
             preuves=[Preuve("GET / (Origin: https://jsi-origine-test.invalid)", r.statut, f"Access-Control-Allow-Origin: {acao}")])


# ---------------------------------------------------------------- chemins exposes
def _txt(r):
    return r.texte if r.ok and r.statut == 200 else ""


def _json_cle(*cles):
    def f(r):
        try:
            d = json.loads(_txt(r))
            return isinstance(d, dict) and any(c in d for c in cles)
        except ValueError:
            return False
    return f


CHEMINS = [
    # (chemin, signature(rep)->bool ou None, gravite, titre, impact, cwe, confiance)
    ("/.git/HEAD", lambda r: _txt(r).strip().startswith("ref:"), Gravite.ELEVEE, "Dépôt Git exposé", "Le code source et l'historique peuvent être récupérés.", "CWE-538", 0.95),
    ("/.env", lambda r: bool(re.search(r"^[A-Z][A-Z0-9_]{2,}=.+", _txt(r), re.M)) and "<html" not in _txt(r)[:300].lower(), Gravite.CRITIQUE, "Fichier .env exposé", "Secrets d'application lisibles publiquement.", "CWE-538", 0.9),
    ("/.DS_Store", lambda r: _txt(r).startswith("\x00\x00\x00\x01Bud1"), Gravite.FAIBLE, ".DS_Store exposé", "Révèle l'arborescence du serveur.", "CWE-538", 0.9),
    ("/server-status", lambda r: "Apache Server Status" in _txt(r), Gravite.MOYENNE, "Page server-status Apache exposée", "Révèle requêtes en cours et clients.", "CWE-200", 0.9),
    ("/phpinfo.php", lambda r: "phpinfo()" in _txt(r) or "PHP Version" in _txt(r), Gravite.MOYENNE, "phpinfo() exposé", "Révèle la configuration serveur.", "CWE-200", 0.9),
    ("/metrics", lambda r: "# HELP" in _txt(r) or "# TYPE" in _txt(r), Gravite.MOYENNE, "Métriques Prometheus exposées sans authentification", "Révèle fonctionnement interne, routes et charge.", "CWE-200", 0.9),
    ("/ftp", lambda r: ("<a href" in _txt(r).lower() and ("listing directory" in _txt(r).lower() or "index of" in _txt(r).lower() or "ftp" in _txt(r).lower()[:600])), Gravite.MOYENNE, "Répertoire de fichiers listable", "Des fichiers internes peuvent être téléchargés.", "CWE-548", 0.7),
    ("/api-docs", lambda r: "swagger" in _txt(r).lower() or "openapi" in _txt(r).lower(), Gravite.FAIBLE, "Documentation d'API exposée", "Cartographie complète de l'API pour un attaquant.", "CWE-200", 0.85),
    ("/swagger.json", _json_cle("swagger", "openapi"), Gravite.FAIBLE, "Spécification OpenAPI exposée", "Cartographie complète de l'API.", "CWE-200", 0.9),
    ("/openapi.json", _json_cle("openapi"), Gravite.FAIBLE, "Spécification OpenAPI exposée", "Cartographie complète de l'API.", "CWE-200", 0.9),
    ("/actuator/env", _json_cle("propertySources", "activeProfiles"), Gravite.ELEVEE, "Spring Actuator /env exposé", "Variables d'environnement lisibles.", "CWE-215", 0.9),
    ("/web.config", lambda r: "<configuration" in _txt(r).lower(), Gravite.ELEVEE, "web.config exposé", "Configuration serveur lisible.", "CWE-538", 0.9),
    # sans signature fiable : confiance faible, filtrees par la reference « page inexistante » puis par l'agent de validation
    ("/admin", None, Gravite.INFO, "Chemin d'administration répondant", "Interface d'administration potentiellement exposée.", "CWE-284", 0.3),
    ("/administration", None, Gravite.INFO, "Chemin d'administration répondant", "Interface d'administration potentiellement exposée.", "CWE-284", 0.3),
    ("/backup", None, Gravite.INFO, "Chemin de sauvegarde répondant", "Des sauvegardes pourraient être accessibles.", "CWE-530", 0.3),
]


def _chemins_exposes(ctx):
    refs = ctx.faits.get("reference_404") or reference_inexistante(ctx)
    base = ctx.cible.url_base()
    for chemin, signature, grav, titre, impact, cwe, conf in CHEMINS:
        ctx.verifier_arret()
        r = ctx.client.request("GET", base + chemin, suivre=False, categorie="web", detail=f"chemin sensible {chemin}")
        if not r.ok or r.statut != 200:
            continue
        if signature is not None:
            if not signature(r):
                continue
            if ressemble_a_reference(r, refs):         # la signature a matche mais c'est la page « tout-venant » : on se mefie
                continue
        else:
            if ressemble_a_reference(r, refs):
                continue                                 # SPA/catch-all : ce n'est pas un chemin reel
        _res(ctx, categorie="chemin-expose", titre=titre, description=f"GET {chemin} répond 200 avec un contenu différent d'une page inexistante.",
             gravite=grav, composant="serveur web", ressource=base + chemin, methode="requête GET + comparaison à la référence 404" +
             (" + signature de contenu" if signature else ""), confiance=conf, impact=impact,
             recommandation="Retirer ou protéger cette ressource (authentification, règle serveur).", references=[cwe],
             cle_validation="chemin_expose", statut=Statut.POTENTIEL if signature else Statut.A_VERIFIER,
             donnees={"url": base + chemin, "chemin": chemin, "signature": bool(signature)},
             preuves=[Preuve(f"GET {chemin}", r.statut, masquer(r.texte[:200]), [f"taille {len(r.corps)} octets", f"type {r.entetes.get('content-type', '?')}"])])


# ---------------------------------------------------------------- formulaires
def _formulaires(ctx, carto):
    for f in carto.formulaires:
        types = [c["type"] for c in f["champs"]]
        url = f["action"]
        if "password" in types and urlsplit(url).scheme == "http":
            _res(ctx, categorie="formulaire", titre="Formulaire de mot de passe transmis sans TLS",
                 description=f"Un champ password est soumis vers {url} en HTTP.", gravite=Gravite.MOYENNE if ctx.cible.type != "local" else Gravite.FAIBLE,
                 composant="formulaire", ressource=url, methode="analyse HTML du formulaire", confiance=0.9,
                 impact="Mot de passe lisible sur le réseau.", recommandation="Servir le site exclusivement en HTTPS.", references=["CWE-319"],
                 cle_validation="formulaire_present", donnees={"page": f["page"]})
        if f["methode"] == "POST" and not any(re.search(r"csrf|token|nonce|authenticity", c["nom"], re.I) for c in f["champs"]):
            _res(ctx, categorie="csrf", titre="Formulaire POST sans jeton anti-CSRF apparent",
                 description=f"Formulaire POST de {f['page']} sans champ jeton visible.", gravite=Gravite.FAIBLE, composant="formulaire",
                 ressource=url, methode="analyse HTML du formulaire (heuristique)", confiance=0.35, statut=Statut.A_VERIFIER,
                 impact="Possible requête intersite forgée (si aucun autre mécanisme : SameSite, en-tête personnalisé).",
                 recommandation="Vérifier la protection CSRF côté serveur ; ajouter un jeton synchronisé.", references=["CWE-352"],
                 cle_validation="formulaire_present", donnees={"page": f["page"]})


# ---------------------------------------------------------------- reflexion d'entree (canari inoffensif) et erreurs SQL
def _cibles_parametres(ctx, carto, maxi=12):
    vus, out = set(), []
    for url, nom in carto.params:
        if (url, nom) not in vus:
            vus.add((url, nom)); out.append((url, nom))
    for ep in sorted(carto.endpoints):                  # heuristique : endpoints de recherche -> parametre « q »
        if re.search(r"search|query|find", ep, re.I) and "${" not in ep and (ctx.cible.url_base() + ep, "q") not in vus:
            out.append((ctx.cible.url_base() + ep, "q"))
    return out[:maxi]


def _entrees(ctx, carto):
    for url, nom in _cibles_parametres(ctx, carto):
        ctx.verifier_arret()
        canari = "jsi" + secrets.token_hex(3)
        sonde = f'{canari}<"\'>'
        r = ctx.client.request("GET", url + "?" + urlencode({nom: sonde}), categorie="web", detail=f"canari sur {nom}")
        if not r.ok:
            continue
        if "html" in r.entetes.get("content-type", "") and f"{canari}<" in r.texte:
            _res(ctx, categorie="xss-reflechi", titre=f"Entrée reflétée sans encodage (paramètre « {nom} »)",
                 description=f"Le canari inoffensif est renvoyé tel quel (caractère < non encodé) dans une page HTML.", gravite=Gravite.MOYENNE,
                 composant="application web", ressource=url, methode="canari inoffensif (aucune charge exécutable)", confiance=0.6,
                 impact="XSS réfléchi possible : exécution de script dans le navigateur de la victime (non démontrée par cet audit).",
                 recommandation="Encoder en sortie selon le contexte (HTML/attribut/JS) ; CSP stricte.", references=["CWE-79"],
                 cle_validation="reflexion", donnees={"url": url, "param": nom},
                 preuves=[Preuve(f"GET {urlsplit(url).path}?{nom}=<canari>", r.statut, "canari reflété avec '<' non encodé")])
        # sonde SQL differentielle : une apostrophe puis deux apostrophes (aucune charge, lecture seule)
        r1 = ctx.client.request("GET", url + "?" + urlencode({nom: "'"}), categorie="web", detail=f"sonde SQL (1) sur {nom}")
        if r1.ok and SIG_SQL.search(r1.texte):
            _res(ctx, categorie="injection-sql", titre=f"Erreur SQL révélée par une apostrophe (paramètre « {nom} »)",
                 description="Une apostrophe isolée provoque une erreur de base de données visible dans la réponse.", gravite=Gravite.ELEVEE,
                 composant="application web / base de données", ressource=url, methode="sonde différentielle ' puis ''", confiance=0.6,
                 impact="Injection SQL probable : lecture/modification de données possible (non exploitée par cet audit).",
                 recommandation="Requêtes préparées/paramétrées ; ne jamais renvoyer les erreurs SQL au client.", references=["CWE-89"],
                 cle_validation="sql_differentiel", donnees={"url": url, "param": nom},
                 preuves=[Preuve(f"GET {urlsplit(url).path}?{nom}='", r1.statut, masquer(_extrait_sql(r1.texte)))])


def _extrait_sql(texte: str) -> str:
    m = SIG_SQL.search(texte)
    return texte[max(0, m.start() - 40): m.end() + 80] if m else texte[:150]


def _erreurs(ctx):
    base = ctx.cible.url_base()
    r = ctx.client.request("GET", base + "/%", suivre=False, categorie="web", detail="gestion d'erreur")
    if r.ok and SIG_TRACE.search(r.texte):
        _res(ctx, categorie="fuite-erreur", titre="Trace d'erreur détaillée renvoyée au client",
             description="Une requête malformée provoque l'affichage d'une trace de pile.", gravite=Gravite.FAIBLE, composant="application web",
             ressource=base + "/%", methode="requête malformée (GET /%)", confiance=0.8,
             impact="Révèle chemins internes, bibliothèques et versions.", recommandation="Désactiver les traces en production ; page d'erreur générique.",
             references=["CWE-209"], cle_validation="trace_erreur", donnees={"url": base + "/%"},
             preuves=[Preuve("GET /%", r.statut, masquer(SIG_TRACE.search(r.texte).group(0)))])


def analyser(ctx, carto=None):
    carto = carto or ctx.carto
    if carto is None or not ctx.faits.get("joignable", False):
        ctx.limiter("analyse web non effectuée : cartographie absente ou cible injoignable")
        return
    for fonction in (lambda: _en_tetes(ctx, carto), lambda: _cookies(ctx, carto), lambda: _cors(ctx),
                     lambda: _chemins_exposes(ctx), lambda: _formulaires(ctx, carto), lambda: _entrees(ctx, carto), lambda: _erreurs(ctx)):
        ctx.verifier_arret()
        fonction()
    ctx.limiter("L'analyse web native ne couvre pas : XSS basé sur le DOM, failles de logique métier, CSRF réel, contrôles d'accès authentifiés (aucune connexion n'est tentée).")
