"""REPORTING AGENT : rapports JSON (complet, machine), HTML (autonome, tout est echappe) et PDF (impression Chromium via Playwright).
Le rapport distingue explicitement : resultats REELS verifies, resultats NON VERIFIES (potentiels, a verifier, non concluants, faux
positifs probables), texte genere par IA (si present, etiquete et jamais source de statut) et limites de l'audit."""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

from modes.ghost_protocol.security.agent_vuln import score, synthese
from modes.ghost_protocol.security.modele import ORDRE_GRAVITE, STATUTS_RETENUS, Gravite, Resultat, Statut

E = html.escape


def construire(session: dict, resultats: list, conseiller_texte: str = "") -> dict:
    """Structure de rapport (source unique pour JSON et HTML)."""
    res = sorted(resultats, key=lambda r: (-ORDRE_GRAVITE[r.gravite], r.statut.value, r.id))
    syn = synthese(res)
    sc = score(res)
    confirmes = [r for r in res if r.statut == Statut.CONFIRME]
    reproduits = [r for r in res if r.statut == Statut.REPRODUIT]
    non_verifies = [r for r in res if r.statut in (Statut.POTENTIEL, Statut.A_VERIFIER, Statut.NON_CONCLUANT)]
    faux = [r for r in res if r.statut == Statut.FAUX_POSITIF]
    recos = {}
    for r in res:
        if r.statut == Statut.FAUX_POSITIF or not r.recommandation:
            continue
        k = r.recommandation
        recos.setdefault(k, {"recommandation": k, "gravite": r.gravite.value, "resultats": []})
        recos[k]["resultats"].append(r.id)
        if ORDRE_GRAVITE[r.gravite] > ORDRE_GRAVITE[Gravite(recos[k]["gravite"])]:
            recos[k]["gravite"] = r.gravite.value
    recos = sorted(recos.values(), key=lambda x: -ORDRE_GRAVITE[Gravite(x["gravite"])])
    return {
        "meta": {"titre": "Rapport d'audit de sécurité — Jarvis Autonomous Security Intelligence", "genere_le": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "session": session.get("id"), "avertissement": "Audit réalisé uniquement dans le périmètre autorisé ci-dessous. Aucun résultat de ce rapport n'est simulé."},
        "perimetre": session["cible"], "environnement": {"observations": session.get("observations", []), "faits": session.get("faits", {})},
        "methodologie": {"etapes": session.get("etapes", []), "ecartees": session.get("ecartees", []), "demandes_validation": session.get("demandes", [])},
        "outils": session.get("outils", {}), "synthese": syn, "risque": sc, "resultats": [r.vers_dict() for r in res],
        "confirmes": [r.id for r in confirmes], "reproduits": [r.id for r in reproduits], "non_verifies": [r.id for r in non_verifies],
        "faux_positifs": [r.id for r in faux], "limites": session.get("limites", []), "recommandations": recos,
        "correlations": session.get("correlations", []), "contradictions": session.get("contradictions", []),
        "synthese_ia": conseiller_texte or "", "duree_s": session.get("duree_s"),
        "conclusion": _conclusion(sc, confirmes, reproduits, non_verifies, session),
    }


def _conclusion(sc, confirmes, reproduits, non_verifies, session) -> str:
    graves = [r for r in confirmes + reproduits if ORDRE_GRAVITE[r.gravite] >= 3]
    t = f"Niveau de risque global estimé : {sc['niveau']} (score indicatif {sc['valeur']}/100). "
    t += f"{len(confirmes)} vulnérabilité(s)/exposition(s) confirmée(s), {len(reproduits)} reproduite(s) sans impact démontré, {len(non_verifies)} résultat(s) non vérifié(s). "
    if graves:
        t += "Priorité : traiter d'abord " + ", ".join(r.id for r in graves[:5]) + ". "
    t += "L'absence de résultat sur un sujet ne prouve pas l'absence de vulnérabilité (voir Limites)."
    return t


def vers_json(rapport: dict) -> str:
    return json.dumps(rapport, ensure_ascii=False, indent=1, default=str)


CSS = """body{font:14px/1.5 system-ui,Segoe UI,Arial,sans-serif;margin:0;background:#f6f7f9;color:#1b1f24}main{max-width:980px;margin:0 auto;padding:28px 22px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;border-bottom:2px solid #1b1f24;padding-bottom:4px;margin:30px 0 10px}h3{font-size:14px;margin:0}
.sub{color:#5b6570}.carte{background:#fff;border:1px solid #d9dde2;border-radius:6px;padding:12px 14px;margin:10px 0;page-break-inside:avoid}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;margin-right:6px;border:1px solid}
.CRITIQUE{background:#7f0000;color:#fff;border-color:#7f0000}.ÉLEVÉE{background:#d32f2f;color:#fff;border-color:#d32f2f}.MOYENNE{background:#f57c00;color:#fff;border-color:#f57c00}
.FAIBLE{background:#fbc02d;color:#222;border-color:#fbc02d}.INFO{background:#e3e8ee;color:#222;border-color:#c9d1da}
.st{background:#fff;color:#222;border-color:#888}.st.conf{border-color:#2e7d32;color:#2e7d32}.st.fp{color:#888;border-style:dashed}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #d9dde2;padding:4px 8px;text-align:left;vertical-align:top}th{background:#eef1f4}
code,pre{font:12px Consolas,monospace;background:#eef1f4;padding:1px 4px;border-radius:3px}pre{padding:8px;white-space:pre-wrap;word-break:break-word}
.alerte{border-left:5px solid #f57c00;background:#fff8e1;padding:8px 12px;margin:10px 0}.ia{border-left:5px solid #7b1fa2;background:#f6ecfa;padding:8px 12px;margin:10px 0}
@media print{body{background:#fff}main{padding:0}}"""


def _badges(r: dict) -> str:
    cls = "conf" if r["statut"] == Statut.CONFIRME.value else ("fp" if r["statut"] == Statut.FAUX_POSITIF.value else "")
    return f'<span class="badge {E(r["gravite"])}">{E(r["gravite"])}</span><span class="badge st {cls}">{E(r["statut"])}</span>'


def _fiche(r: dict) -> str:
    preuves = "".join(f"<li><code>{E(p.get('requete', ''))}</code> {('HTTP ' + str(p['statut_http'])) if p.get('statut_http') else ''} — {E(p.get('extrait', ''))} {E(' ; '.join(p.get('observations') or []))}</li>" for p in r["preuves"])
    hist = "".join(f"<li>{E(h['de'])} → {E(h['vers'])} : {E(h['motif'])}</li>" for h in r["historique_statut"])
    return (f'<div class="carte" id="{E(r["id"])}"><h3>{E(r["id"])} — {E(r["titre"])}</h3><p>{_badges(r)}<span class="sub">{E(r["categorie"])} · agent {E(r["agent"])} · confiance {round(r["confiance"] * 100)} %</span></p>'
            f'<p>{E(r["description"])}</p><table><tr><th>Composant</th><td>{E(r["composant"])}</td></tr><tr><th>Ressource</th><td><code>{E(r["ressource"])}</code></td></tr>'
            f'<tr><th>Méthode de détection</th><td>{E(r["methode"])}</td></tr><tr><th>Impact potentiel</th><td>{E(r["impact"])}</td></tr>'
            f'<tr><th>Recommandation</th><td>{E(r["recommandation"])}</td></tr><tr><th>Références</th><td>{E(", ".join(r["references"]) or "—")}</td></tr></table>'
            f'<p><b>Preuves techniques minimales</b></p><ul>{preuves or "<li>aucune</li>"}</ul><p><b>Historique de validation</b></p><ul>{hist or "<li>—</li>"}</ul></div>')


def vers_html(rp: dict) -> str:
    m, p = rp["meta"], rp["perimetre"]
    res = rp["resultats"]
    ids = lambda cle: set(rp[cle])
    def section(titre, cle):
        liste = [r for r in res if r["id"] in ids(cle)]
        return f"<h2>{E(titre)} ({len(liste)})</h2>" + ("".join(_fiche(r) for r in liste) or '<p class="sub">Aucun.</p>')
    outils = "".join(f"<tr><td>{E(n)}</td><td>{E(o['statut'])}</td><td>{E(o.get('version') or '—')}</td><td>{E(o.get('note', ''))}</td><td>{'oui' if o.get('utilise') else 'non'}</td></tr>" for n, o in rp["outils"].items())
    etapes = "".join(f"<tr><td>{E(e['cle'])}</td><td>{E(e['statut'])}</td><td>{E(e.get('pourquoi', ''))}</td><td>{E(str(e.get('resume', ''))[:200])}</td></tr>" for e in rp["methodologie"]["etapes"])
    ecart = "".join(f"<tr><td>{E(e['cle'])}</td><td>{E(e['raison'])}</td></tr>" for e in rp["methodologie"]["ecartees"])
    dem = "".join(f"<li>{E(d)}</li>" for d in rp["methodologie"]["demandes_validation"])
    sg = rp["synthese"]
    matrice = "".join(f"<tr><td>{E(k)}</td><td>{v}</td></tr>" for k, v in sorted(sg["par_gravite"].items(), key=lambda kv: -ORDRE_GRAVITE[Gravite(kv[0])]))
    matrice_s = "".join(f"<tr><td>{E(k)}</td><td>{v}</td></tr>" for k, v in sg["par_statut"].items())
    recos = "".join(f'<li><span class="badge {E(r["gravite"])}">{E(r["gravite"])}</span>{E(r["recommandation"])} <span class="sub">({E(", ".join(r["resultats"][:6]))})</span></li>' for r in rp["recommandations"])
    obs = "".join(f"<li>{E(o)}</li>" for o in rp["environnement"]["observations"])
    lim = "".join(f"<li>{E(l)}</li>" for l in rp["limites"])
    ia = f'<div class="ia"><b>Synthèse rédigée par un modèle d’IA — NON VÉRIFIÉE, sans effet sur les statuts :</b><br>{E(rp["synthese_ia"])}</div>' if rp["synthese_ia"] else ""
    corr = "".join(f"<li>{E(c)}</li>" for c in rp["correlations"] + [f"contradiction : {x}" for x in rp["contradictions"]])
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{E(m['titre'])}</title><style>{CSS}</style></head><body><main>
<h1>{E(m['titre'])}</h1><p class="sub">Session {E(str(m['session']))} · généré le {E(m['genere_le'])}</p>
<div class="alerte"><b>Résultats réels :</b> {E(m['avertissement'])} Les éléments « potentiel », « à vérifier » et « non concluant » ci-dessous sont des <b>hypothèses non vérifiées</b>.</div>
<h2>1. Résumé exécutif</h2><p>{E(rp['conclusion'])}</p><table><tr><th>Gravité</th><th>Nombre</th></tr>{matrice}</table><br><table><tr><th>Statut</th><th>Nombre</th></tr>{matrice_s}</table>{ia}
<h2>2. Périmètre autorisé</h2><table><tr><th>Cible</th><td><code>{E(str(p.get('hote')))}</code> ports {E(str(p.get('ports')))} ({E(str(p.get('type')))}, {E(str(p.get('plateforme')))})</td></tr>
<tr><th>Identifiant d'autorisation</th><td>{E(str(p.get('id')))}</td></tr><tr><th>Attestation</th><td>{E(str(p.get('attestation')))}</td></tr>
<tr><th>Autorisation valable jusqu'au</th><td>{E(time.strftime('%Y-%m-%d %H:%M', time.localtime(p.get('expire_le', 0))))}</td></tr><tr><th>Catégories autorisées</th><td>{E(', '.join(p.get('actions', [])))}</td></tr></table>
<p class="sub">Garde-fous : méthodes GET/HEAD/OPTIONS uniquement, aucune authentification ni écriture, limitation de débit, journalisation, arrêt d'urgence.</p>
<h2>3. Environnement testé</h2><ul>{obs or '<li>—</li>'}</ul>
<h2>4. Méthodologie et décisions du moteur</h2><table><tr><th>Étape</th><th>Statut</th><th>Justification</th><th>Résumé</th></tr>{etapes}</table>
<p><b>Étapes écartées</b></p><table><tr><th>Étape</th><th>Raison</th></tr>{ecart or '<tr><td colspan=2>aucune</td></tr>'}</table>{('<p><b>Demandes de validation (non exécutées)</b></p><ul>' + dem + '</ul>') if dem else ''}
<h2>5. Outils utilisés et versions</h2><table><tr><th>Outil</th><th>Statut réel</th><th>Version</th><th>Note</th><th>Utilisé dans cet audit</th></tr>{outils}</table>
{section('6. Vulnérabilités confirmées', 'confirmes')}{section('7. Vulnérabilités reproduites (impact non démontré)', 'reproduits')}{section('8. Résultats non vérifiés (hypothèses)', 'non_verifies')}{section('9. Faux positifs probables (écartés)', 'faux_positifs')}
<h2>10. Corrélations</h2><ul>{corr or '<li>aucune</li>'}</ul>
<h2>11. Recommandations (par priorité)</h2><ul>{recos or '<li>—</li>'}</ul>
<h2>12. Limites de l'audit</h2><ul>{lim or '<li>—</li>'}</ul>
<h2>Conclusion</h2><p>{E(rp['conclusion'])}</p></main></body></html>"""


def vers_pdf(chemin_html: Path, chemin_pdf: Path) -> tuple:
    """(ok, message). PDF par impression Chromium (Playwright) ; sinon message explicite, jamais de faux PDF."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright absent : PDF non généré (uv run playwright install chromium)"
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch()
            page = nav.new_page()
            page.goto(Path(chemin_html).resolve().as_uri())
            page.pdf(path=str(chemin_pdf), format="A4", print_background=True, margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
            nav.close()
        return True, "PDF généré"
    except Exception as e:
        return False, f"PDF non généré ({type(e).__name__}: {str(e)[:100]})"
