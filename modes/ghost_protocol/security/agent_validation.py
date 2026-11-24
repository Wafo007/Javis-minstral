"""VALIDATION AGENT : reverifie chaque resultat par une NOUVELLE observation independante (jamais en relisant la premiere).

Regles de promotion (deterministes, documentees dans docs/ARCHITECTURE_SECURITY_INTELLIGENCE.md) :
  * CONFIRME  : le constat est une observation directe reproduite (config, exposition de contenu a signature, differentiel SQL...) ;
  * REPRODUIT : meme constat obtenu une seconde fois, mais l'impact reel n'est pas demontre (reflexion d'entree, secret non teste...) ;
  * FAUX_POSITIF : la reverification contredit (ex. page « tout-venant » d'une SPA) ; NON_CONCLUANT : erreur/ambiguite ;
  * inchange (POTENTIEL / A_VERIFIER) : aucune reverification independante possible -> dit explicitement.
Un LLM ne participe jamais a cette etape."""
from __future__ import annotations

import re
import secrets
import socket
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from modes.ghost_protocol.security import agent_web as web
from modes.ghost_protocol.security.contexte import AuditInterrompu
from modes.ghost_protocol.security.modele import Preuve, Resultat, Statut, masquer
from modes.ghost_protocol.security.perimetre import RefusPerimetre

RX_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
RX_LOGIN = re.compile(r"(?i)type=[\"']?password|<form[^>]*login|name=[\"']?(user|login|email)")


def _get(ctx, url, entetes=None, suivre=False, methode="GET", cat=""):
    return ctx.client.request(methode, url, entetes, suivre=suivre, categorie=cat or "web", detail="validation")


def v_entete_absent(ctx, r):
    url, nom, alt = r.donnees["url"], r.donnees["entete"], r.donnees.get("alt", "")
    g1, g2 = _get(ctx, url), _get(ctx, url)
    if not (g1.ok and g2.ok):
        return Statut.NON_CONCLUANT, "reverification impossible (erreur réseau)", []

    def absent(rep):
        return nom not in rep.entetes and not (alt and alt in rep.entetes.get("content-security-policy", ""))
    if not (absent(g1) and absent(g2)):
        return Statut.FAUX_POSITIF, f"l'en-tête {nom} est présent lors de la reverification", []
    h = _get(ctx, url, methode="HEAD")
    pr = [Preuve("GET / (x2)", g1.statut, f"{nom} absent des deux réponses")]
    if h.ok and absent(h):
        return Statut.CONFIRME, "absence observée sur GET, GET et HEAD (3 requêtes indépendantes)", pr + [Preuve("HEAD /", h.statut, f"{nom} absent")]
    return Statut.REPRODUIT, "absence reproduite sur 2 GET (HEAD non concordant)", pr


def v_entete_present(ctx, r):
    g = _get(ctx, r.donnees["url"])
    if not g.ok:
        return Statut.NON_CONCLUANT, "reverification impossible", []
    v = g.entetes.get(r.donnees["entete"], "")
    if v and v == r.donnees["valeur"]:
        return Statut.CONFIRME, "en-tête identique relevé à nouveau", [Preuve("GET /", g.statut, f"{r.donnees['entete']}: {v}")]
    return Statut.FAUX_POSITIF, "l'en-tête n'est plus présent ou a changé", []


def v_cookie(ctx, r):
    g = _get(ctx, r.donnees["url"])
    nom = r.donnees["cookie"]
    ligne = next((c for c in g.cookies if c.split("=", 1)[0].strip() == nom), None) if g.ok else None
    if ligne is None:
        return Statut.NON_CONCLUANT, "le cookie n'a pas été réémis lors de la reverification", []
    bas = ligne.lower()
    toujours = [x for x in r.donnees["manque"] if x.lower() not in bas and not (x == "Secure" and ctx.cible.schema != "https")]
    if toujours:
        return Statut.CONFIRME, f"cookie réémis sans {', '.join(toujours)}", [Preuve("GET", g.statut, masquer(ligne.split(";", 1)[-1]))]
    return Statut.FAUX_POSITIF, "attributs présents lors de la reverification", []


def v_cors(ctx, r):
    o2 = "https://jsi-autre-origine.invalid"
    g = _get(ctx, r.donnees["url"], {"Origin": o2})
    acao = g.entetes.get("access-control-allow-origin", "") if g.ok else ""
    if acao in (o2, "*"):
        return Statut.CONFIRME, "politique permissive reproduite avec une autre origine", [Preuve("GET (Origin différente)", g.statut, f"Access-Control-Allow-Origin: {acao}")]
    return (Statut.NON_CONCLUANT if not g.ok else Statut.FAUX_POSITIF), "comportement non reproduit avec une autre origine", []


def v_chemin(ctx, r):
    refs = ctx.faits.get("reference_404") or web.reference_inexistante(ctx)
    g = _get(ctx, r.donnees["url"])
    if not g.ok or g.statut != 200:
        return Statut.FAUX_POSITIF if g.ok else Statut.NON_CONCLUANT, f"la ressource ne répond plus 200 ({g.statut or g.erreur})", []
    if web.ressemble_a_reference(g, refs):
        return Statut.FAUX_POSITIF, "la réponse est identique à celle d'une page inexistante (application « catch-all »)", []
    sig = next((c[1] for c in web.CHEMINS if c[0] == r.donnees["chemin"]), None)
    pr = [Preuve(f"GET {r.donnees['chemin']}", g.statut, masquer(g.texte[:160]))]
    if sig is not None:
        if sig(g):
            return (Statut.CONFIRME if r.confiance >= 0.85 else Statut.REPRODUIT), "signature de contenu reproduite", pr
        return Statut.FAUX_POSITIF, "la signature de contenu n'est plus retrouvée", []
    if RX_LOGIN.search(g.texte):
        return Statut.NON_CONCLUANT, "la page est un écran de connexion : aucun accès démontré", pr
    return Statut.REPRODUIT, "réponse différente d'une page inexistante, reproduite ; sensibilité à confirmer manuellement", pr


def v_reflexion(ctx, r):
    canari = "jsi" + secrets.token_hex(3)
    g = _get(ctx, r.donnees["url"] + "?" + urlencode({r.donnees["param"]: f'{canari}<"\'>'}))
    if g.ok and "html" in g.entetes.get("content-type", "") and f"{canari}<" in g.texte:
        csp = g.entetes.get("content-security-policy", "")
        note = " ; une CSP est présente (mitigation à évaluer)" if csp else ""
        return Statut.REPRODUIT, "réflexion non encodée reproduite avec un nouveau canari ; exécution de script NON démontrée" + note, [Preuve("GET (nouveau canari)", g.statut, "'<' non encodé")]
    return Statut.FAUX_POSITIF if g.ok else Statut.NON_CONCLUANT, "réflexion non reproduite", []


def v_sql(ctx, r):
    u, p = r.donnees["url"], r.donnees["param"]
    a = _get(ctx, u + "?" + urlencode({p: "'"}))
    b = _get(ctx, u + "?" + urlencode({p: "''"}))
    c = _get(ctx, u + "?" + urlencode({p: "jsi"}))
    if not (a.ok and b.ok and c.ok):
        return Statut.NON_CONCLUANT, "reverification impossible", []
    ea, eb, ec = (bool(web.SIG_SQL.search(x.texte)) for x in (a, b, c))
    pr = [Preuve("GET ?p='", a.statut, "erreur SQL" if ea else "pas d'erreur"), Preuve("GET ?p=''", b.statut, "erreur SQL" if eb else "pas d'erreur"),
          Preuve("GET ?p=jsi", c.statut, "erreur SQL" if ec else "pas d'erreur")]
    if ea and not eb and not ec:
        return Statut.CONFIRME, "comportement différentiel : erreur SQL avec ' seulement (pas avec '' ni avec une valeur neutre)", pr
    if ea and (eb or ec):
        return Statut.NON_CONCLUANT, "erreur présente aussi sans apostrophe isolée : non différentiel", pr
    return Statut.FAUX_POSITIF, "erreur SQL non reproduite", pr


def v_trace(ctx, r):
    g = _get(ctx, r.donnees["url"])
    if g.ok and web.SIG_TRACE.search(g.texte):
        return Statut.CONFIRME, "trace d'erreur reproduite", [Preuve("GET /%", g.statut, masquer(web.SIG_TRACE.search(g.texte).group(0)))]
    return Statut.FAUX_POSITIF if g.ok else Statut.NON_CONCLUANT, "trace non reproduite", []


def v_formulaire(ctx, r):
    if r.categorie == "csrf":
        return None                                    # heuristique : seule une revue manuelle peut conclure
    g = _get(ctx, r.donnees["page"])
    if g.ok and re.search(r"type=[\"']?password", g.texte, re.I):
        return Statut.CONFIRME, "champ mot de passe toujours servi en HTTP", [Preuve("GET page", g.statut, "champ password présent, schéma http")]
    return Statut.FAUX_POSITIF if g.ok else Statut.NON_CONCLUANT, "formulaire non retrouvé", []


def v_api_non_auth(ctx, r):
    g = _get(ctx, r.donnees["url"], cat="api")
    if not g.ok or g.statut != 200:
        return (Statut.FAUX_POSITIF if g.ok else Statut.NON_CONCLUANT), f"accès non reproduit ({g.statut or g.erreur})", []
    mails = RX_EMAIL.findall(g.texte)
    pr = [Preuve(f"GET {r.donnees['ep']} (sans authentification)", g.statut, masquer(g.texte[:160]), [f"{len(mails)} adresse(s) e-mail dans la réponse (masquées)"])]
    if mails:
        return Statut.CONFIRME, "accès anonyme reproduit ET données personnelles (adresses e-mail) présentes", pr
    return Statut.REPRODUIT, "accès anonyme reproduit ; caractère sensible des données non démontré (peut être public par conception)", pr


def v_api_500(ctx, r):
    g = _get(ctx, r.donnees["url"], cat="api")
    if g.ok and g.statut >= 500:
        return Statut.REPRODUIT, f"HTTP {g.statut} reproduit", [Preuve("GET", g.statut, masquer(g.texte[:120]))]
    return Statut.FAUX_POSITIF if g.ok else Statut.NON_CONCLUANT, "erreur serveur non reproduite", []


def v_api_options(ctx, r):
    g = _get(ctx, r.donnees["url"], methode="OPTIONS", cat="api")
    allow = (g.entetes.get("allow") or g.entetes.get("access-control-allow-methods") or "") if g.ok else ""
    if any(m in allow.upper() for m in r.donnees["methodes"]):
        return Statut.REPRODUIT, "méthodes annoncées reproduites (leur effet réel n'est pas testé : l'audit n'écrit jamais)", [Preuve("OPTIONS", g.statut, allow[:100])]
    return Statut.FAUX_POSITIF if g.ok else Statut.NON_CONCLUANT, "annonce non reproduite", []


def v_port(ctx, r):
    try:
        ctx.garde.autoriser("tcp_connect", r.donnees["hote"], None, "", f"reverification port {r.donnees['port']}", "reseau")
        with socket.create_connection((r.donnees["hote"], r.donnees["port"]), timeout=2):
            return Statut.CONFIRME, "connexion TCP acceptée à nouveau", [Preuve("TCP connect", None, "connexion acceptée")]
    except RefusPerimetre:
        raise
    except OSError:
        return Statut.FAUX_POSITIF, "le port n'accepte plus les connexions", []


def v_tls(ctx, r):
    import ssl
    v = {"TLSv1": ssl.TLSVersion.TLSv1, "TLSv1.1": ssl.TLSVersion.TLSv1_1}[r.donnees["version"]]
    try:
        ctx.garde.autoriser("tls_handshake", r.donnees["hote"], r.donnees["port"], "", "reverification TLS", "reseau")
        c = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        c.check_hostname, c.verify_mode, c.minimum_version, c.maximum_version = False, ssl.CERT_NONE, v, v
        c.set_ciphers("ALL:@SECLEVEL=0")
        with socket.create_connection((r.donnees["hote"], r.donnees["port"]), timeout=3) as s, c.wrap_socket(s, server_hostname=r.donnees["hote"]):
            return Statut.CONFIRME, "poignée de main reproduite", [Preuve("handshake", None, r.donnees["version"] + " accepté")]
    except RefusPerimetre:
        raise
    except (OSError, ssl.SSLError, ValueError):
        return Statut.FAUX_POSITIF, "protocole refusé lors de la reverification", []


def _contexte_test(chemin: str) -> bool:
    return bool(re.search(r"(?i)(^|/)(tests?|__tests__|spec|specs|examples?|samples?|fixtures?|mocks?|docs?|e2e|cypress|data/static)(/|$)|\.(example|sample|md)$", chemin))


def v_secret(ctx, r):
    d = r.donnees
    racine = d.get("racine") or ctx.cible.chemin_code
    f = Path(racine) / d["fichier"]
    try:
        lignes = f.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return Statut.NON_CONCLUANT, "fichier illisible lors de la reverification", []
    i = int(d.get("ligne") or 0)
    if not (0 < i <= len(lignes)):
        return Statut.NON_CONCLUANT, "ligne introuvable (fichier modifié ?)", []
    if _contexte_test(d["fichier"]) and d.get("regle") == "affectation-secrete":
        return Statut.FAUX_POSITIF, "valeur située dans un dossier de tests/exemples/documentation : probablement factice", []
    ligne = lignes[i - 1]
    present = any(rx.search(ligne) for _, rx, _ in __import__("modes.ghost_protocol.security.agent_code", fromlist=["x"]).MOTIFS_SECRETS) or \
        bool(__import__("modes.ghost_protocol.security.agent_code", fromlist=["x"]).RX_AFFECTATION.search(ligne)) or d.get("regle") not in (None, "affectation-secrete")
    if present:
        return Statut.REPRODUIT, "le motif est toujours présent ; la validité du secret n'est PAS testée (volontairement) donc jamais « confirmé »", [Preuve(f"{d['fichier']}:{i}", None, "motif retrouvé (valeur non conservée)")]
    return Statut.NON_CONCLUANT, "le motif n'est plus présent à cette ligne", []


def v_regle_code(ctx, r):
    from modes.ghost_protocol.security.agent_code import REGLES
    d = r.donnees
    try:
        lignes = (Path(d["racine"]) / d["fichier"]).read_text(encoding="utf-8", errors="replace").splitlines()
        rx = next(x[2] for x in REGLES if x[0] == d["regle"])
        ok = rx.search(lignes[int(d["ligne"]) - 1]) is not None
    except (OSError, IndexError, StopIteration, KeyError):
        return Statut.NON_CONCLUANT, "fichier/ligne introuvable", []
    if not ok:
        return Statut.NON_CONCLUANT, "motif absent à la reverification", []
    if _contexte_test(d["fichier"]):
        return Statut.NON_CONCLUANT, "motif réel mais situé dans des tests/exemples : risque probablement nul", [Preuve(d["fichier"], None, "motif retrouvé")]
    return Statut.REPRODUIT, "motif retrouvé ; exploitabilité non démontrée (dépend de la provenance des données)", [Preuve(d["fichier"], None, "motif retrouvé")]


def v_dependance(ctx, r):
    t = ctx.faits.get("osv_transport")
    if not t or "ids" not in r.donnees:
        return None
    try:
        rep = t("https://api.osv.dev/v1/query", {"package": {"name": r.donnees["paquet"], "ecosystem": r.donnees["ecosysteme"]}, "version": r.donnees["version"]})
    except Exception:
        return Statut.NON_CONCLUANT, "seconde requête OSV impossible", []
    ids = {v.get("id") for v in rep.get("vulns", [])}
    if ids & set(r.donnees["ids"]):
        return Statut.REPRODUIT, "avis retrouvés lors d'une seconde interrogation indépendante ; exploitabilité non évaluée", [Preuve("OSV query", None, ", ".join(sorted(ids & set(r.donnees["ids"])))[:120])]
    return Statut.FAUX_POSITIF, "avis non retrouvés", []


def v_nuclei(ctx, r):
    from modes.ghost_protocol.security import outils as O
    o = (ctx.faits.get("outils") or {}).get("nuclei")
    mod = O._templates_nuclei()
    if not o or o.statut != "operationnel" or not mod or not r.donnees.get("template"):
        return None
    ex = O.executer([o.chemin, "-u", r.donnees["url"], "-id", r.donnees["template"], "-t", mod, "-jsonl", "-silent", "-duc", "-ni", "-nc", "-rl", "5", "-timeout", "8", "-retries", "0"],
                    ctx.arret, 120)
    trouves, _ = O.parser_nuclei(ex.sortie, ctx.cible.hote)
    if any(x.donnees.get("template") == r.donnees["template"] for x in trouves):
        return Statut.REPRODUIT, "le modèle nuclei correspond à nouveau (2e exécution) ; non confirmé par une preuve indépendante", [Preuve("nuclei -id " + r.donnees["template"], None, "correspondance reproduite")]
    return (Statut.FAUX_POSITIF if ex.code == 0 else Statut.NON_CONCLUANT), "le modèle ne correspond plus lors de la 2e exécution", []


VALIDATEURS = {"entete_absent": v_entete_absent, "entete_present": v_entete_present, "cookie_attributs": v_cookie, "cors": v_cors,
               "chemin_expose": v_chemin, "reflexion": v_reflexion, "sql_differentiel": v_sql, "trace_erreur": v_trace, "formulaire_present": v_formulaire,
               "api_non_auth": v_api_non_auth, "api_500": v_api_500, "api_options": v_api_options, "port_ouvert": v_port, "tls_ancien": v_tls,
               "secret_fichier": v_secret, "regle_code": v_regle_code, "dependance": v_dependance, "nuclei": v_nuclei}


def valider(ctx, filtre=None) -> dict:
    """Valide tous les resultats (ou ceux de `filtre`). Renvoie les compteurs de transitions."""
    bilan = {"valides": 0, "inchanges": 0, "faux_positifs": 0, "confirmes": 0, "reproduits": 0, "non_concluants": 0}
    for r in list(ctx.resultats.values()):
        ctx.verifier_arret()
        if r.statut in (Statut.CONFIRME, Statut.FAUX_POSITIF) or (filtre and not filtre(r)):
            continue
        fn = VALIDATEURS.get(r.cle_validation)
        if fn is None:
            bilan["inchanges"] += 1
            r.historique_statut.append({"de": r.statut.value, "vers": r.statut.value, "motif": "aucune reverification indépendante possible (résultat d'un seul outil)", "t": 0})
            continue
        try:
            sortie = fn(ctx, r)
        except RefusPerimetre:
            raise AuditInterrompu("refus du périmètre pendant la validation")
        except AuditInterrompu:
            raise
        except Exception as e:
            sortie = (Statut.NON_CONCLUANT, f"erreur de validation : {type(e).__name__}", [])
        if sortie is None:
            bilan["inchanges"] += 1
            r.historique_statut.append({"de": r.statut.value, "vers": r.statut.value, "motif": "reverification indépendante indisponible dans cet environnement", "t": 0})
            continue
        statut, motif, preuves = sortie
        r.changer_statut(statut, motif)
        r.preuves.extend(p for p in preuves if p not in r.preuves)
        bilan["valides"] += 1
        bilan[{Statut.FAUX_POSITIF: "faux_positifs", Statut.CONFIRME: "confirmes", Statut.REPRODUIT: "reproduits", Statut.NON_CONCLUANT: "non_concluants"}.get(statut, "inchanges")] += 1
        ctx.journal.ecrire("VALIDATION", id=r.id, statut=statut.value, motif=motif)
        ctx.emettre("resultat", r)
    return bilan
