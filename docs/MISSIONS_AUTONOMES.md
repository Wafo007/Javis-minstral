# Missions autonomes d'auto-amélioration

> « Jarvis, améliore ton système de routage. Tu disposes de 60 minutes. »
> Jarvis crée un espace de travail isolé, analyse son code, planifie, modifie de vrais fichiers, lance de vrais tests,
> corrige, s'arrête à l'heure, prépare une version candidate, écrit un rapport et te prévient. **La version stable n'est
> jamais touchée.**

## 1. Audit initial (état du projet avant ce travail)

| Mécanisme existant | Où | Décision |
|---|---|---|
| Cycle auto-modification **en place** (branche → écriture → diff → tests → commit → retour arrière), chemins protégés | `core/auto_modification.py`, `tools/mon_code.py` (outils vocaux N2/N3), `scripts/auto_modif.py` | **Étendu**, pas remplacé : on y ajoute les briques `git worktree` (workspace isolé, checkpoint, intégration autorisée) et on réutilise `chemin_autorise` / `PROTEGES_*`. Le cycle interactif existant (« modifie ton code ») reste intact. |
| Délégation de tâches longues à Hermes (fichiers JSON + thread) | `tools/deleguer_a_hermes.py` | **Non réutilisée** : Hermes ne doit pas détenir les clés ni exécuter d'actions sensibles (doctrine du projet) ; une mission doit modifier du code localement, avec Mistral/Gemini gratuits uniquement. |
| Routage 3 étages (commandes locales → `decider_prioritaire` → LLM) | `core/routage_intentions.py` | Un routeur `router_mission` est inséré **en premier** dans la liste des routeurs déterministes ; il ne capte que les phrases de mission (voir §5). |
| Permissions N1/N2/N3 | `core/registre.py` | `mission_integrer` ajouté en N3 ; les outils de mission sont `_NON_LOCAUX` (besoin du cloud). |
| Clients Mistral/Gemini, suivi d'usage | `core/cloud.py` | Réutilisés tels quels par `core/fournisseurs_mission.py`. |
| Notification Windows, supervision de processus longs, base de missions | **absents** | Créés (`core/missions.py`). |

## 2. Architecture

```
voix ─► router_mission ─► tools/missions.py ─► core/missions.py ──► SQLite (missions.db)
                                                   │ lance (processus détaché)
                                                   ▼
                          scripts/mission_worker.py ─► core/mission_agent.py (boucle)
                                                   │            │ LLM = décision JSON seulement
                                                   │            ▼
                                                   │   core/fournisseurs_mission.py (Mistral/Gemini : 429, backoff, bascule, budgets)
                                                   ▼
        <racine>/workspaces/mission_NNN  (git worktree, branche jarvis/mission_NNN)
        <racine>/reports/mission_NNN     (report.md, changes.diff, tests.json, execution.log)
```

`<racine>` = `missions.racine` ou `%LOCALAPPDATA%\JarvisMissions`. La « version stable » est le projet lui-même.

**Modules** : `core/missions.py` (base, machine à états, horloge, supervision, notification) ·
`core/mission_agent.py` (boucle, confinement, tests) · `core/fournisseurs_mission.py` · `core/mission_rapport.py` ·
`scripts/mission_worker.py` · `tools/missions.py` · extensions `core/auto_modification.py`.

**États** : `PENDING RUNNING TESTING PAUSED WAITING_FOR_QUOTA` (actifs) ; `COMPLETED PARTIAL FAILED CANCELLED TIMEOUT`
(terminaux, définitifs). Les transitions sont validées en base (`TRANSITIONS`) ; une transition incohérente lève une erreur.

**Boucle** (une action JSON par tour du LLM) : OBSERVE (contexte déterministe : fichiers pertinents classés sans LLM) →
PLAN (`update_plan`) → EDIT (`write_file`, `replace_in_file`, `delete_file`) → TEST (`run_tests`, `validate`,
`run_command`, `benchmark`) → EVALUATE → RETRY_OR_FINISH. Chaque itération est écrite en base **et** dans
`execution.log`, p. ex. `{"step":4,"action":"write_file","target":"core/x.py","success":true,"verified":false,"tests":[],"error":null}`.

**Ce que fait Python et non le LLM** : confinement des chemins, écriture + **relecture sur disque**, compilation, suite de
tests complète comparée à la **baseline** (tests passés avant qui échouent, **disparaissent** ou deviennent *skipped* = régression),
points de contrôle git, retour au dernier état vérifié, rapport, horloge, notification. Une modification n'est `verified`
qu'après une validation verte ; les modifications non vérifiées sont **écartées de la branche candidate** (diff conservé dans
`changes_non_verifiees.diff`).

**Durée** : défaut 60 min, plafond 120 min (jamais dépassé), c'est un plafond. Temps *actif* monotone, persisté au battement
de cœur ; pauses et attentes de quota non comptées ; plafond calendaire séparé (24 h). À l'échéance : plus aucune nouvelle
modification (contrôle aussi après chaque appel LLM), arrêt propre, travail vérifié conservé, rapport partiel, état `TIMEOUT`.

**Quotas gratuits** : détection 429/5xx/timeout, `Retry-After` (secondes ou date HTTP) jamais anticipé, backoff exponentiel
+ gigue 25 %, bascule vers l'autre fournisseur seulement s'il n'est pas lui-même en quarantaine, essais bornés, budgets
(requêtes, tokens, étapes). Si tout est bloqué plus de `attente_inline_max_s` : `WAITING_FOR_QUOTA`, état sauvegardé, reprise
automatique (le worker reste vivant et surveille annulation/échéance).

**Reprise** : si le processus meurt (plantage, redémarrage de Windows), `reprendre_interrompues()` (appelée au démarrage de
Jarvis) relance le worker ; il reprend depuis la base : plan, baseline (non refaite), compteurs, dernier checkpoint ; le LLM
est averti que la dernière étape est peut-être partielle. Les missions en pause restent en pause.

**Sécurité** : écriture uniquement dans le workspace ; chemins absolus hors workspace, `..`, liens symboliques sortants, `.git`
→ refusés. Fichiers protégés (`config.yaml`, `.env`, secrets, verrous de sécurité, **modules du moteur eux-mêmes**) jamais
modifiables. Commandes : liste blanche (pytest, compileall, py_compile, pyflakes, `ruff check`, timeit, git en lecture), jamais
de shell, pas d'installation. Sous-processus avec environnement purgé de tout nom contenant KEY/TOKEN/SECRET/PASSWORD/AUTH/
COOKIE (et `GIT_CONFIG_*`). Les secrets ne sont jamais recopiés dans le workspace. Une action non autorisée **n'est pas contournée** :
elle est inscrite dans « actions nécessitant une autorisation » (§17 du rapport), l'étape est mise en attente, la mission
continue sur le reste. L'intégration dans la version stable = outil **N3** `mission_integrer` (confirmation vocale à chaque
fois) → `git apply` du diff vérifié, sans commit. Aucun test ne peut être supprimé, désactivé ou affaibli.

## 3. Utilisation

| Tu dis | Effet |
|---|---|
| « Jarvis, améliore ton système de routage. Tu disposes de 60 minutes. » | démarre une mission (60 min) |
| « analyse ton code source et améliore ton routage… tu disposes de deux heures » | démarre (120 min) |
| « améliore ton code pendant une heure » / « corrige les problèmes de routage pendant deux heures » | démarre |
| « analyse ton système de mémoire » / « lance une campagne d'auto-amélioration » | démarre (durée par défaut) |
| « où en est ta mission ? » | statut (construit depuis la base) |
| « mets ta mission en pause » / « reprends ta mission » | pause après l'étape en cours / reprise |
| « annule la mission » / « arrêt d'urgence de la mission » | arrêt propre / arrêt immédiat de l'arbre de processus |
| « montre-moi ton rapport » | résumé + chemin de `report.md` |
| « applique les modifications de la mission » | intégration N3 (confirmation) |

Les mots de contrôle Windows (ouvre, tape, clique…) ne déclenchent jamais une mission. Une mission est lancée seulement si la
phrase contient un verbe d'amélioration **et** une cible « Jarvis » (code, routage, mémoire…) **et** un indice de mission
longue (durée, « mission », « campagne », « tu disposes de »…) ou « analyse ton… ». « améliore ton code » seul reste le
cycle interactif existant.

Configuration : bloc `missions:` de `config.example.yaml` (durée, budgets, fournisseurs, timeouts, `commande_tests`).
Clés Mistral/Gemini : uniquement dans `config.yaml`, jamais dans le chat.

## 4. Guide de validation sur Windows (à faire par toi — non vérifiable depuis le sandbox)

1. `uv sync` puis `uv run pytest tests/test_missions.py -q` : doit passer (ces tests créent de vrais dépôts git temporaires ;
   `test_annulation…` et `test_worker_detache…` exercent de vrais processus).
2. Vérifier `git --version` (≥ 2.20 pour `git worktree`). Le projet doit être un dépôt git avec au moins un commit.
3. Lancer Jarvis, dire : « Jarvis, analyse ton système de routage. Tu disposes de 10 minutes. » Attendre « C'est parti ».
4. Dire « où en est ta mission ? » ; ouvrir `%LOCALAPPDATA%\JarvisMissions\reports\mission_001\execution.log` (suivi en direct).
5. **Fermer la fenêtre de Jarvis** : le processus `python.exe … mission_worker.py` doit continuer (Gestionnaire des tâches).
6. Tuer ce processus (fin de tâche) puis relancer Jarvis : le message « Missions reprises après interruption » doit apparaître.
7. Provoquer un quota (clé gratuite saturée) : état `WAITING_FOR_QUOTA` puis reprise automatique.
8. À la fin : info-bulle Windows + annonce vocale. **L'info-bulle est « émise » si PowerShell répond sans erreur ; son affichage
   réel n'est pas vérifiable par le code** (si elle n'apparaît pas, désactive l'assistant de concentration Windows).
9. Relire `changes.diff`, relancer les tests dans le workspace, puis « applique les modifications de la mission ».

## 5. Limites connues (honnêtes)

- **Non testé sur Windows ni avec les vrais Mistral/Gemini** : tout a été exécuté sous Linux avec un LLM *scripté* (doublure
  explicitement étiquetée). La qualité réelle des modifications dépend du modèle gratuit ; le moteur garantit seulement qu'une
  modification n'est jamais déclarée vérifiée sans tests verts et sans régression par rapport à la baseline.
- Le détachement Windows (`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`), `taskkill`/psutil et l'info-bulle PowerShell n'ont pas
  pu être exercés ici.
- Pas de session « bureau » : le moteur n'utilise ni souris ni VS Code (fichiers, git, terminal uniquement).
- Les tests lents du projet (≈ 50 s la suite complète) sont relancés à chaque `validate` : prévoir un budget de temps réaliste.
- Les benchmarks avant/après n'existent que pour un script `bench*.py` présent dans la version de base ; sinon aucun gain de
  performance n'est affirmé (le rapport le dit).
- `psutil` est utilisé s'il est présent (déjà dans les dépendances du projet) ; sinon repli `taskkill`/`kill`.
- Dépendances : Python, uv, Git, SQLite, pytest — rien de payant, aucun Visual C++ ni outil de compilation requis.

## 6. Exemple réel

`docs/exemples/mission_exemple/` : mission exécutée sur une copie du vrai projet (vrai worktree, vraie suite pytest complète :
baseline 541 réussis / 4 erreurs d'environnement connues ; validations vertes sans régression ; le LLM est une doublure scriptée).
On y voit : une docstring améliorée + un test ajouté vérifiés et commités sur le candidat, une tentative d'écraser un test par du
code invalide **refusée** (état final `PARTIAL` : 1 action attend ton autorisation), le rapport en 17 sections et la mention
« notification NON livrée » (plateforme Linux).
