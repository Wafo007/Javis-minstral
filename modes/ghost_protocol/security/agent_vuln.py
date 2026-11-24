"""VULNERABILITY AGENT : classification, correlation et score de risque (regles deterministes, apres validation)."""
from __future__ import annotations

from modes.ghost_protocol.security.modele import ORDRE_GRAVITE, STATUTS_RETENUS, Gravite, Resultat, Statut

CWE_PAR_CATEGORIE = {"xss-reflechi": "CWE-79", "injection-sql": "CWE-89", "controle-acces": "CWE-862", "secret-expose": "CWE-798", "cors": "CWE-942",
                     "cookies": "CWE-1004", "clickjacking": "CWE-1021", "chemin-expose": "CWE-538", "fuite-erreur": "CWE-209", "tls": "CWE-326",
                     "en-tetes-securite": "CWE-693", "service-expose": "CWE-668", "dependance-vulnerable": "CWE-1104"}
POIDS_STATUT = {Statut.CONFIRME: 1.0, Statut.REPRODUIT: 0.7, Statut.A_VERIFIER: 0.35, Statut.POTENTIEL: 0.3, Statut.NON_CONCLUANT: 0.1, Statut.FAUX_POSITIF: 0.0}


def _monter(r: Resultat, grav: Gravite, motif: str):
    if ORDRE_GRAVITE[grav] > ORDRE_GRAVITE[r.gravite]:
        r.historique_statut.append({"de": r.gravite.value, "vers": grav.value, "motif": "gravité relevée par corrélation : " + motif, "t": 0})
        r.gravite = grav


def correler(ctx) -> dict:
    res = list(ctx.resultats.values())
    correlations = []
    for r in res:
        if not any(x.startswith("CWE") for x in r.references) and r.categorie in CWE_PAR_CATEGORIE:
            r.references.append(CWE_PAR_CATEGORIE[r.categorie])
    csp_absente = any(r.categorie == "en-tetes-securite" and "Content-Security-Policy" in r.titre and r.statut in STATUTS_RETENUS for r in res)
    for r in res:
        if r.statut == Statut.FAUX_POSITIF:
            continue
        if r.categorie == "xss-reflechi" and r.statut in STATUTS_RETENUS and csp_absente:
            _monter(r, Gravite.ELEVEE, "réflexion d'entrée reproduite ET aucune CSP pour la limiter")
            correlations.append(f"{r.id} : XSS réfléchi aggravé par l'absence de CSP")
        if r.categorie == "injection-sql" and r.statut == Statut.CONFIRME:
            _monter(r, Gravite.CRITIQUE, "différentiel SQL confirmé")
            correlations.append(f"{r.id} : injection SQL confirmée par différentiel")
        if r.categorie == "controle-acces" and r.statut == Statut.CONFIRME:
            _monter(r, Gravite.ELEVEE, "données personnelles lisibles sans authentification")
            correlations.append(f"{r.id} : exposition de données personnelles")
        if r.categorie == "cookies" and r.statut == Statut.CONFIRME and any(x.categorie == "xss-reflechi" and x.statut in STATUTS_RETENUS for x in res):
            _monter(r, Gravite.ELEVEE, "cookie lisible par script ET XSS reproduit : vol de session plausible")
            correlations.append(f"{r.id} : cookie sans HttpOnly + XSS reproduit")
    # contradictions entre resultats d'une meme ressource : le plus fort est declasse, a verifier manuellement
    par_res = {}
    for r in res:
        par_res.setdefault((r.categorie, r.ressource), []).append(r)
    contradictions = []
    for cle, groupe in par_res.items():
        if len({x.statut for x in groupe}) > 1 and any(x.statut == Statut.CONFIRME for x in groupe) and any(x.statut in (Statut.FAUX_POSITIF, Statut.NON_CONCLUANT) for x in groupe):
            for x in groupe:
                if x.statut == Statut.CONFIRME:
                    x.changer_statut(Statut.REPRODUIT, "résultats contradictoires sur la même ressource : vérification manuelle requise")
            contradictions.append(f"{cle[0]} @ {cle[1]}")
    return {"correlations": correlations, "contradictions": contradictions, "score": score(res)}


def score(res) -> dict:
    """Score de risque 0..100 : somme ponderee (gravite x confiance x poids du statut), saturee. Indicatif, pas une mesure absolue."""
    brut = sum((ORDRE_GRAVITE[r.gravite] + 0.5) * r.confiance * POIDS_STATUT[r.statut] for r in res if r.gravite != Gravite.INFO)
    note = min(100, round(brut * 4))
    niveau = "CRITIQUE" if any(r.gravite == Gravite.CRITIQUE and r.statut in STATUTS_RETENUS for r in res) else \
        "ÉLEVÉ" if note >= 60 or any(r.gravite == Gravite.ELEVEE and r.statut in STATUTS_RETENUS for r in res) else "MODÉRÉ" if note >= 25 else "FAIBLE"
    return {"valeur": note, "niveau": niveau}


def synthese(res) -> dict:
    par_statut, par_grav = {}, {}
    for r in res:
        par_statut[r.statut.value] = par_statut.get(r.statut.value, 0) + 1
        par_grav[r.gravite.value] = par_grav.get(r.gravite.value, 0) + 1
    return {"total": len(res), "par_statut": par_statut, "par_gravite": par_grav,
            "confirmes": [r.id for r in res if r.statut == Statut.CONFIRME],
            "potentiels": [r.id for r in res if r.statut in (Statut.POTENTIEL, Statut.A_VERIFIER)]}
