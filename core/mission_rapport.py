"""Rapport de mission deterministe : report.md, changes.diff, tests.json, execution.log.

Genere UNIQUEMENT a partir de la base (etapes, tests reellement executes, mesures) et de git : aucun LLM, aucun
resultat invente. Chaque modification est classee verifiee / non verifiee / partielle / en echec.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from core import auto_modification as am
from core import missions as M


def _hm(s) -> str:
    s = int(max(0, s or 0))
    return f"{s // 3600} h {s % 3600 // 60:02d} min {s % 60:02d} s" if s >= 3600 else f"{s // 60} min {s % 60:02d} s"


def _ts(t) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else "-"


def generer_rapport(store: M.MissionStore, mid: str) -> Path:
    m = store.get(mid)
    dossier = Path(m["rapports"])
    dossier.mkdir(parents=True, exist_ok=True)
    etapes, tests, mesures = store.etapes(mid), store.tests(mid), store.mesures(mid)
    ws, base, cp = m.get("workspace"), m.get("base_commit"), m.get("dernier_checkpoint")

    # -- diff verifie (base -> dernier checkpoint) : c'est le candidat
    diff = ""
    fichiers_verifies = []
    try:
        if ws and Path(ws).is_dir() and base and cp and base != cp:
            diff = am._git(ws, "diff", base, cp).stdout
            fichiers_verifies = [l for l in am._git(ws, "diff", "--name-only", base, cp).stdout.splitlines() if l]
    except Exception as exc:                                            # le rapport ne doit jamais echouer
        diff = f"# diff indisponible : {exc}\n"
    (dossier / "changes.diff").write_text(diff, encoding="utf-8")
    non_verifie = dossier / "changes_non_verifiees.diff"

    (dossier / "tests.json").write_text(json.dumps([
        {"etape": t["etape"], "nature": t["nature"], "commande": json.loads(t["commande"]) if t["commande"] else [],
         "code_retour": t["rc"], "statut": t["statut"], "duree_s": round(t["duree"], 2), "resume": t["resume"],
         "stdout": t["stdout"], "stderr": t["stderr"], "date": _ts(t["ts"])} for t in tests],
        ensure_ascii=False, indent=2), encoding="utf-8")
    journal = dossier / "execution.log"
    if not journal.exists():
        journal.write_text("", encoding="utf-8")

    modifs = [e for e in etapes if e["action"] in ("write_file", "replace_in_file", "delete_file")]
    lus = sorted({e["cible"] for e in etapes if e["action"] in ("read_file", "list_files") and e["cible"]})
    echecs = [e for e in etapes if not e["succes"]]
    corrections = []                       # echec suivi d'un succes sur la meme cible
    for i, e in enumerate(etapes):
        if not e["succes"] and any(x["succes"] and x["cible"] == e["cible"] and x["action"] == e["action"]
                                   for x in etapes[i + 1:]):
            corrections.append(e)
    autor = m.get("autorisations") or []
    statuts_tests = {}
    for t in tests:
        statuts_tests[t["statut"]] = statuts_tests.get(t["statut"], 0) + 1
    non_exec = [t for t in tests if t["statut"] == "non_executable"]

    L = [f"# Rapport de mission {m['id']}", ""]
    L += ["## 1. Objectif", m["objectif"], ""]
    L += ["## 2. Durée prévue", _hm(m["duree_max_s"]) + " (plafond, pas une obligation)", ""]
    L += ["## 3. Durée réelle",
          f"{_hm(m['temps_actif_s'])} de temps actif (pauses et attentes de quota non comptées) ; "
          f"du {_ts(m['demarre_le'])} au {_ts(m['termine_le'])}", ""]
    L += ["## 4. Étapes réalisées", f"{len(etapes)} étape(s) enregistrée(s), dont {len(echecs)} en échec.", ""]
    for e in etapes[-60:]:
        L.append(f"- #{e['n']} {e['phase']} `{e['action']}` {e['cible'] or ''} → "
                 f"{'OK' if e['succes'] else 'ÉCHEC'}{' (vérifié par tests)' if e['verifie'] else ''}"
                 + (f" — {e['erreur']}" if e["erreur"] else ""))
    L += ["", "## 5. Fichiers analysés"] + ([f"- {x}" for x in lus[:60]] or ["- aucun"]) + [""]
    L += ["## 6. Fichiers modifiés (candidat vérifié)"] + ([f"- {x}" for x in fichiers_verifies] or ["- aucun"]) + [""]
    L += ["## 7. Modifications effectuées"]
    for e in modifs:
        etat = ("VÉRIFIÉE" if e["verifie"] else "NON VÉRIFIÉE (écartée du candidat)") if e["succes"] else "ÉCHEC"
        L.append(f"- #{e['n']} `{e['action']}` {e['cible']} : {etat}")
    if not modifs:
        L.append("- aucune")
    if non_verifie.exists():
        L.append(f"- Les modifications non vérifiées ont été écartées de la branche candidate et conservées dans "
                 f"`{non_verifie.name}`.")
    L += [""]
    L += ["## 8. Problèmes rencontrés"] + ([f"- #{e['n']} `{e['action']}` {e['cible'] or ''} : {e['erreur'] or 'échec'}"
                                              for e in echecs[:30]] or ["- aucun"]) + [""]
    L += ["## 9. Corrections appliquées"] + ([f"- #{e['n']} `{e['action']}` {e['cible']} corrigé ensuite"
                                                for e in corrections] or ["- aucune"]) + [""]
    L += ["## 10. Tests exécutés", f"{len(tests)} exécution(s) réelle(s) ; statuts : "
          + (", ".join(f"{k}={v}" for k, v in statuts_tests.items()) or "aucune") + ". Détails complets dans `tests.json`."]
    for t in tests[-25:]:
        L.append(f"- étape {t['etape']} [{t['nature']}] `{' '.join(json.loads(t['commande'])[1:6])}` → "
                 f"{t['statut']} (rc={t['rc']}, {t['duree']:.1f}s) {t['resume'] or ''}")
    L += [""]
    valides = [e for e in modifs if e["verifie"]]
    L += ["## 11. Résultats", f"- Modifications vérifiées : {len(valides)} / {len([e for e in modifs if e['succes']])} réussies.",
          f"- Tests non exécutables dans cet environnement : {len(non_exec)} exécution(s)." if non_exec else
          "- Tous les tests lancés ont pu s'exécuter.", ""]
    L += ["## 12. Améliorations mesurées"]
    if mesures:
        for x in mesures:
            L.append(f"- {x['nom']} : avant {x['avant']:.4f} {x['unite']}, après {x['apres']:.4f} {x['unite']} "
                     f"(`{x['commande']}`)")
    else:
        L.append("- Aucune mesure avant/après réalisée : aucun gain de performance n'est affirmé.")
    L += ["", "## 13. Erreurs non résolues"]
    L += ([f"- {e['cible'] or e['action']} : {e['erreur']}" for e in echecs[-8:] if e["erreur"] not in (None, "invalide")]
          or ["- aucune connue"]) + [""]
    L += ["## 14. État final", f"**{m['statut']}** — {m.get('resume') or ''}",
          f"Notification : {m.get('notification') or 'non tentée'}", ""]
    L += ["## 15. Branche Git", f"- Branche candidate : `{m.get('branche')}` (workspace `{m.get('workspace')}`)",
          f"- Base : `{(base or '')[:10]}` → dernier point de contrôle vérifié : `{(cp or '')[:10]}`",
          "- La version stable n'a PAS été modifiée.", ""]
    L += ["## 16. Instructions de validation",
          f"1. Relire le diff : `{dossier / 'changes.diff'}`.",
          f"2. Dans le workspace, relancer les tests : `cd {m.get('workspace')}` puis `uv run pytest -q`.",
          "3. Pour intégrer : dire « applique les modifications de la mission » (confirmation vocale N3) "
          "ou `git apply changes.diff` dans le projet.",
          "4. Pour abandonner : supprimer le workspace et la branche (`git worktree remove`, `git branch -D`).", ""]
    L += ["## 17. Actions nécessitant une autorisation"]
    L += ([f"- étape {a['etape']} `{a['action']}` {a['cible']} : {a['raison']}" for a in autor] or ["- aucune"])
    L += ["- L'intégration dans la version stable exige toujours une autorisation explicite.", ""]
    (dossier / "report.md").write_text("\n".join(L), encoding="utf-8")
    return dossier / "report.md"
