"""MOTEUR DE DECISION : choisit l'etape suivante d'apres le TYPE de cible, les FAITS decouverts, les OUTILS reellement
disponibles et le perimetre autorise. Entierement deterministe : le LLM ne peut que SUGGERER des etapes d'un catalogue ferme
(il n'ecrit ni commande, ni cible). Chaque decision porte sa justification ; les etapes ecartees sont consignees avec leur raison."""
from __future__ import annotations

from dataclasses import dataclass

CATALOGUE = {
    "recon": "Reconnaissance et cartographie", "web": "Analyse de sécurité web", "api": "Analyse de sécurité API",
    "reseau": "Analyse réseau", "nuclei": "Détection nuclei (modèles non intrusifs)", "zap": "OWASP ZAP baseline (passif)",
    "code": "Analyse statique native du code", "gitleaks": "Recherche de secrets (gitleaks)", "semgrep": "Analyse statique semgrep",
    "trivy": "Analyse trivy (dépendances/secrets)", "depcheck": "OWASP Dependency-Check",
    "validation": "Validation des résultats", "correlation": "Classification et corrélation", "rapport": "Génération du rapport",
}
TYPES_WEB = {"local", "reseau_prive", "lab_portswigger", "externe"}
TYPES_AVEC_SCAN_PORTS = {"local", "reseau_prive"}        # hotes mutualises de tiers (labs web PortSwigger, externes) : pas de scan de ports
ETAPES_ACTIVES = {"recon", "web", "api", "reseau", "nuclei", "zap"}


@dataclass
class Etape:
    cle: str
    titre: str
    pourquoi: str
    agent: str = ""


@dataclass
class Ecartee:
    cle: str
    raison: str


def _outil_ok(outils: dict, nom: str) -> bool:
    o = outils.get(nom)
    return bool(o and o.statut == "operationnel")


def _nuclei_utilisable(outils: dict) -> bool:
    if not _outil_ok(outils, "nuclei"):
        return False
    from modes.ghost_protocol.security import outils as O
    return bool(O._templates_nuclei())


def suivante(cible, outils: dict, faits: dict, faites: dict, ecartees: list, conseils=(), garde=None, client=None):
    """Renvoie (Etape | None, raison_arret). `faites` : cle -> statut. `ecartees` est completee en place."""
    def deja(cle):
        return cle in faites or any(e.cle == cle for e in ecartees)

    def ecarter(cle, raison):
        if not deja(cle):
            ecartees.append(Ecartee(cle, raison))

    if client is not None and client.erreurs_consecutives >= 5:
        return None, "la cible ne répond plus (5 erreurs réseau consécutives) : audit arrêté"
    epuise = garde is not None and garde.compte >= garde.budget
    code = cible.type == "code_local"
    conseils = set(conseils or ())

    if code:
        if not deja("gitleaks"):
            if _outil_ok(outils, "gitleaks"):
                return Etape("gitleaks", CATALOGUE["gitleaks"], "gitleaks est opérationnel : détection de secrets plus complète que les motifs natifs", "OUTIL"), ""
            ecarter("gitleaks", "gitleaks absent : les secrets sont recherchés par l'analyse native (moins complète)")
        if not deja("code"):
            return Etape("code", CATALOGUE["code"], "Analyse statique native : motifs dangereux" + ("" if "gitleaks" in faites else ", secrets")
                         + " et dépendances (OSV)", "CODE"), ""
        if not deja("semgrep"):
            if _outil_ok(outils, "semgrep"):
                return Etape("semgrep", CATALOGUE["semgrep"], "semgrep opérationnel : analyse de flux plus fine que les motifs natifs", "OUTIL"), ""
            ecarter("semgrep", "semgrep absent ou en erreur")
        if not deja("trivy"):
            if not _outil_ok(outils, "trivy"):
                ecarter("trivy", "trivy absent")
            elif (faits.get("code") or {}).get("verifie"):
                ecarter("trivy", "dépendances déjà vérifiées via OSV (évite un test redondant)")
            else:
                return Etape("trivy", CATALOGUE["trivy"], "les dépendances n'ont pas été vérifiées via OSV : trivy prend le relais (secrets au minimum)", "OUTIL"), ""
        if not deja("depcheck"):
            if _outil_ok(outils, "dependency-check") and "depcheck" in conseils:
                return Etape("depcheck", CATALOGUE["depcheck"], "demandé par le conseiller et outil opérationnel (première exécution très longue)", "OUTIL"), ""
            ecarter("depcheck", "dependency-check absent, ou non demandé (téléchargement NVD très long)")
        return _fin(faites)

    # ---- cible reseau/web
    if not deja("recon"):
        return Etape("recon", CATALOGUE["recon"], "Première étape obligatoire : vérifier que la cible répond et cartographier ce qui est accessible", "RECON"), ""
    if faits.get("joignable") is False:
        for k in ("web", "api", "reseau", "nuclei", "zap"):
            ecarter(k, "cible injoignable")
        return _fin(faites, ignorer_actives=True)
    if epuise:
        for k in ETAPES_ACTIVES:
            ecarter(k, "budget de requêtes épuisé")
    if not deja("web"):
        if faits.get("pages", 0) > 0:
            return Etape("web", CATALOGUE["web"], f"{faits.get('pages')} page(s) cartographiée(s) : vérification des en-têtes, cookies, CORS, chemins exposés, formulaires, entrées", "WEB"), ""
        ecarter("web", "aucune page web exploitable découverte")
    if not deja("api"):
        if faits.get("a_api"):
            return Etape("api", CATALOGUE["api"], f"{faits.get('endpoints', 0)} endpoint(s) d'API repéré(s) dans le code client : contrôle d'accès non authentifié", "API"), ""
        ecarter("api", "aucun endpoint d'API repéré par la reconnaissance")
    if not deja("reseau"):
        if "reseau" not in cible.actions:
            ecarter("reseau", "action « reseau » non autorisée pour cette cible (demande de validation créée)")
        elif cible.type not in TYPES_AVEC_SCAN_PORTS:
            ecarter("reseau", "hôte mutualisé appartenant à un tiers : aucun scan de ports (tests web uniquement)")
        else:
            moteur = "nmap" if _outil_ok(outils, "nmap") else "scan TCP natif"
            return Etape("reseau", CATALOGUE["reseau"], f"Cible de type {cible.type} : inventaire des ports exposés ({moteur})", "RESEAU"), ""
    if not deja("nuclei"):
        if "outils" not in cible.actions:
            ecarter("nuclei", "catégorie « outils » non autorisée")
        elif _nuclei_utilisable(outils):
            return Etape("nuclei", CATALOGUE["nuclei"], "nuclei opérationnel avec modèles locaux : détections d'exposition/configuration, sans modèles d'attaque", "OUTIL"), ""
        else:
            ecarter("nuclei", "nuclei absent, en erreur, ou modèles nuclei-templates introuvables")
    if not deja("zap"):
        if _outil_ok(outils, "zap") and "outils" in cible.actions:
            return Etape("zap", CATALOGUE["zap"], "ZAP baseline opérationnel : analyse passive complémentaire", "OUTIL"), ""
        ecarter("zap", "ZAP absent ou mode baseline indisponible")
    return _fin(faites)


def _fin(faites, ignorer_actives=False):
    for cle in ("validation", "correlation", "rapport"):
        if cle not in faites:
            titres = {"validation": "Reverifier chaque résultat par une observation indépendante (promotion/rétrogradation de statut)",
                      "correlation": "Classer, corréler et noter les résultats", "rapport": "Produire le rapport HTML, JSON et PDF"}
            return Etape(cle, CATALOGUE[cle], titres[cle], {"validation": "VALIDATION", "correlation": "VULN", "rapport": "RAPPORT"}[cle]), ""
    return None, "audit terminé : toutes les étapes pertinentes sont faites"
