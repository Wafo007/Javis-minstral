# Jarvis — Rapport d'audit technique et de correction

Date : 22–23 octobre 2026 · Base : `Javis-minstral.zip` (HEAD git `c5767d8`) · Référence : `JARVIS_PLAN_CORRECTION.pdf` (S1–S10)

## 0. Lecture honnête en 30 secondes

- **Ce qui est prouvé** : la logique du code corrigé, par 117 nouveaux tests automatisés (+ 12 tests existants rendus exécutables). Suite complète : **469 réussis, 0 échec**, contre **340 réussis / 15 échecs** avant correction (même machine, même méthode).
- **Ce qui n'est PAS prouvé** : le comportement réel sur Windows. Cet environnement est Linux : aucune fenêtre, aucun `SetForegroundWindow`, aucun `SendInput`, aucune UI Automation, aucun Get-StartApps n'a été exécuté pour de vrai. Tout ce qui touche Windows est testé avec des doubles (mocks). **Un mock n'est pas une validation Windows.**
- **Ce qui reste à faire de ton côté** : lancer `scripts/valider_windows.py --actions-reelles` sur ton PC (5 minutes) et me renvoyer le JSON produit. C'est la seule façon de transformer les « corrigé mais non vérifiable ici » en « corrigé et testé ».
- **Le projet n'est pas déclaré entièrement corrigé** : voir §6 (problèmes non résolus).

## 1. Architecture réelle du projet

Assistant vocal Python 3.13 / uv, ~22 000 lignes. Chaîne : wake word (openWakeWord) → STT (faster-whisper / OpenAI) → routage → LLM (Mistral, Gemini en secours, OpenAI, Anthropic, Ollama) → outils → TTS.

| Couche | Fichiers | Rôle |
|---|---|---|
| Point d'entrée | `jarvis14.py` (1654 l.) | boucle vocale, prompt système, exécution des outils, confirmations |
| Routage | `core/commandes_locales.py` → `core/routage_intentions.py` (`decider_prioritaire`) → LLM filtré par `modules_pour_phrase` | 3 étages : commandes locales, routes déterministes (Alexa, média, apps, contrôle PC, colis, Astra, Hermes), puis LLM avec catalogue d'outils réduit |
| Registre | `core/registre.py` | décorateur `@outil`, niveaux N1/N2/N3 (`_N3`), confirmation vocale, `mcp_expose` |
| Contrôle PC | `tools/controle_pc.py` (ctypes + PowerShell/UIA), `tools/souris.py`, `tools/systeme.py`, `tools/apps.py` | fenêtres, clavier, clics par nom, lancement d'applications |
| Astra | `tools/astra_pc.py` + `core/cloud.decider_action_vision` | opérateur visuel (capture → décision → action), N3 |
| Navigateur | `tools/navigateur.py`, `core/playwright_partage.py` | Chrome dédié via CDP + Playwright |
| Hermes | `tools/deleguer_a_hermes.py` | délégation en fond, suivi des tâches |

Composants du brief **absents** du code (non inventés) : Vosk, ElevenLabs côté outils de contrôle, « registre dynamique » au sens d'un plan d'exécution. Il n'existait **aucun outil de fichiers** ni **aucun mécanisme d'auto-modification**.

## 2. Méthode

1. Copie intacte conservée (`baseline_original/`) + historique git du projet. 2. Baseline des tests sur la copie intacte. 3. Lecture intégrale des fichiers du plan. 4. `git log` pour dater les régressions. 5. Correction minimale, une cause racine à la fois. 6. Tests de non-régression écrits **avant** de déclarer chaque correction. 7. Suite complète relancée à chaque étape.

Particularité : les fichiers du dépôt sont en **CRLF** (le working tree entier apparaissait « modifié » dans git). Les fins de ligne d'origine sont restaurées dans l'archive livrée.

## 3. Causes racines trouvées

### 3.1 Régressions introduites par les deux derniers commits (« try fix jarvix control fail », « gemini vision »)

| # | Défaut | Preuve | Correction |
|---|---|---|---|
| R1 | `core/cloud.py::decider_action_vision` : `secours_actif` défini seulement dans la branche Mistral → `UnboundLocalError` **avant tout appel réseau** avec OpenAI ou Anthropic (Astra inutilisable avec ces fournisseurs) | `test_openai_provider` échouait à la baseline | défini pour tous les fournisseurs |
| R2 | même fonction : `statut = getattr(e, …)` **hors** du `except` → `UnboundLocalError` à la première erreur Mistral (le repli 429 → modèle suivant ne marchait jamais) | `test_action_vision_secours_sur_429` échouait | logique déplacée dans le `except`, comportement d'origine rétabli (essai du modèle suivant) |
| R3 | `core/routage_intentions.py` : le domaine « média » n'offrait pas `controle_pc` ; « tape… » ne déclenchait aucun domaine PC | 2 tests échouaient | domaines corrigés |
| R4 | `core/contexte.py` : la consigne multi-actions avait été raccourcie (perte de « dans l'ordre, puis résume ») | `test_correction_dans_la_consigne` | consigne restaurée + règles Bloc-notes et honnêteté ajoutées |
| R5 | `tools/controle_pc.py` : `ctypes.windll` à l'import → module non importable hors Windows (tests, CI) | `test_astra_pc` en erreur de collecte | garde `EST_WINDOWS`, erreur claire à l'usage |

### 3.2 Scénario « Ouvre le Bloc-notes et écris… » (problème prioritaire n°1)

Chaîne réelle de la phrase `Jarvis, ouvre le Bloc-notes et écris : Bonjour, je suis Jarvis, assistant intelligent.` — **six défauts cumulés** :

1. **Confusion `noter`** : `modules_pour_phrase` cherchait « note » par sous-chaîne → « Bloc‑**notes** » déclenchait le domaine `notes`. Le LLM ne recevait alors que `noter` (+ `reponses`). Cause directe de la confusion décrite. → « bloc-notes » neutralisé avant la détection, domaine « applications PC » ajouté, descriptions de `noter` / `taper_texte` rendues explicitement disjointes, règle ajoutée au prompt système et à la consigne.
2. **« Jarvis, » cassait la chaîne** : la virgule suivant l'appel était prise pour un connecteur de commandes ; « Jarvis » devenait une étape non routable → `router_commande_pc` renvoyait `None` → repli sur le LLM. → nom d'appel retiré avant découpage.
3. **Ponctuation perdue** : le texte à taper était reconstruit depuis des mots nus (« Bonjour je suis Jarvis assistant intelligent »). → extraction depuis la phrase brute (virgules, point, accents, casse conservés).
4. **Texte dicté découpé** : « écris Marie et Paul, ouvre la porte » était coupé en deux commandes. → après un verbe de dictée on ne coupe plus que sur « puis / ensuite / et enregistre ».
5. **Aucune vérification d'ouverture** : `ouvrir_application` / `launch_app` faisaient `os.startfile` puis répondaient « lancé ». `lancer_application_pc` ignorait le résultat de `_attendre_fenetre` et répondait « est ouvert » même sans fenêtre. → la fenêtre est constatée ; sinon message d'échec honnête (`« J'ai lancé X, mais je ne vois pas sa fenêtre apparaître »`).
6. **Faux succès du focus** : `_activer` renvoyait la fenêtre même quand Windows refusait le premier plan (simple log d'avertissement) → le texte partait dans la mauvaise fenêtre, ou le LLM concluait « pas ouvert » alors qu'elle l'était. → `SetForegroundWindow` renforcé (restauration, `AttachThreadInput`, 3 essais) puis **relecture de `GetForegroundWindow`** ; état exposé, jamais présenté comme succès s'il est faux.

Et pour la saisie elle-même : `SendInput` n'était pas contrôlé (échec = « C'est tapé »), les caractères hors BMP (emoji) étaient tronqués, aucune cible n'était vérifiée. → retour de `SendInput` contrôlé, paires de substitution UTF‑16, paramètre `fenetre`, refus de taper dans un terminal, **relecture du texte via UI Automation** (message « vérifié » ou « non vérifié » selon le cas).

### 3.3 Autres défauts

| Section | Défaut | Correction |
|---|---|---|
| S1 | `_apps_demarrer` mettait **`[]` en cache à vie** après un échec de `Get-StartApps` (cause plausible de « liste du menu Démarrer vide » persistante) ; sortie PowerShell décodée en UTF‑8 sans forcer l'encodage | pas de cache d'échec (nouvel essai après 60 s), encodage UTF‑8 forcé, secours : liste fermée d'utilitaires intégrés, registre `App Paths`, `PATH` |
| S1 | fenêtres « cloaked » (UWP suspendues) listées ; « bloc‑notes » ≠ « bloc notes » ; terminal demandé introuvable | filtre DWM, normalisation tiret/espace, alias terminal |
| S2 | `_controles` (UIA) lancé dans un PowerShell **non DPI‑aware** : sur un écran à 125/150 %, les coordonnées UIA sont virtualisées → clics par nom à côté | `SetProcessDPIAware` avant UIA |
| S2 | `cliquer_bouton` ignorait le retour de `_placer_curseur` et n'apportait aucune preuve | position du curseur relue (tolérance 3 px) avant le clic ; l'**effet** du clic n'est pas affirmé (`verifie=False`) |
| S4 | Astra : `termine` pris pour un fait ; messages d'échec de `cliquer_ecran` traités comme des succès | vérification finale par un second regard (config `astra_pc.verification_finale`), détection d'écran inchangé (arrêt après 3), arrêt après 3 échecs |
| S3 | `scripts/diagnostic_pc.py` testait seulement `import playwright` (OK même si `_greenlet` est cassé) ; API synchrone appelée depuis un autre thread = erreur obscure | `diagnostiquer()` exécute la chaîne complète ; `PlaywrightIndisponible` explicite ; `expliquer_erreur()` (greenlet/VC++, Chromium absent) branchée dans `navigateur._absent()` |
| S5 | aucun outil de fichiers | `tools/fichiers.py` (voir §4) |
| S7 | réponse vide d'Hermes → « Hermes a terminé. (réponse vide) » ; aucune vérification du livrable ; échecs absents du suivi vocal ; bascule HTTP→CLI silencieuse | réponse vide = échec ; `livrable` vérifié (existe, non vide, lisible) ; statut `partielle` ; échecs listés par `taches_hermes` ; bascule journalisée |
| S8 | `enchainer_commandes` annonçait « s'arrête à la première qui échoue » mais **ne le faisait pas** ; le texte tapé n'était pas lié à l'application ouverte avant | arrêt réel sur échec ; l'application de l'étape d'ouverture est transmise à la saisie/clic suivants |
| S9 | inexistant | `core/auto_modification.py` + CLI |

## 4. Nouveaux composants (aucune nouvelle dépendance)

- `core/resultat.py` — `ResultatOutil(str)` : sous-classe de `str` (tout l'existant continue de marcher) portant `succes`, `verifie`, `details`, `erreur`. `est_echec()` reconnaît aussi les formules d'échec des outils historiques.
- `tools/fichiers.py` — `fichier_lister/lire` (N1), `fichier_ecrire/deplacer` (N2), `fichier_supprimer` (**N3**, ajouté à `_N3` dans `registre.py`). Confinement dans `fichiers.racines` (défaut `~/Documents/Jarvis`), chemins résolus (liens symboliques, `..`, UNC refusés), secrets refusés, écriture atomique + `.bak`, relecture de contrôle, suppression = déplacement en `.corbeille_jarvis` (récupérable). Jamais exposés au MCP.
- `core/auto_modification.py` + `scripts/auto_modif.py` — cycle branche dédiée → écriture (chemins protégés) → diff → tests → commit **seulement si vert** → redémarrage supervisé → retour arrière complet. Pas de fusion automatique, **non branché à la voix** (décision volontaire).
- `scripts/valider_windows.py` — validation réelle (voir `INSTRUCTIONS_WINDOWS_UV.md`).

## 5. Sécurité préservée

- Niveaux de permission inchangés ; `controle_pc_astra`, `ajouter_app` restent N3 ; seul ajout : `fichier_supprimer` en N3. Test dédié (`TestSecuritePreservee`, `test_permissions`).
- Aucune protection désactivée pour faire passer un test. `_SENSIBLES` (clics payer/supprimer…), `_INTERDITES` (Ctrl+Alt+Suppr), garde-fous Astra : intacts et testés.
- Aucun secret lu, affiché ou ajouté. `config.example.yaml` : 3 clés ajoutées, valeurs génériques.
- Nouveau refus : `taper_texte` n'écrit plus dans un terminal (évite qu'un « entrée » exécute une commande) — réglable par `controle_pc.autoriser_terminal`.

## 6. Problèmes NON résolus / limites

1. **Aucune validation Windows réelle.** Toutes les sections S1, S2 et la partie « applications » de S5 restent *« corrigé mais non vérifiable sur cet environnement »*. Le PowerShell UIA (relecture, DPI), `SetForegroundWindow`/`AttachThreadInput`, `SendInput` et `App Paths` n'ont jamais tourné ici. Ils ont été relus mais peuvent contenir une erreur que seul Windows révélera.
2. **Cause exacte de l'échec `_greenlet` sur ton PC : inconnue.** Ici la chaîne Playwright complète s'exécute avec succès (Playwright 1.56 installé, le projet demande ≥ 1.62). Je ne peux que fournir le diagnostic et le message de remède (VC++ 2015‑2022, réinstallation de greenlet).
3. **Deux modules de tests non exécutés** (`test_securite_lot1.py`, `test_poste_distant_route.py`) : ils exigent `fastapi`, introuvable ici (PyPI bloqué par le proxy). Ce sont des tests de **sécurité** : relance-les chez toi (`uv run pytest`). Deux autres modules (`test_agent_affichage`, `test_satellite_audio`) n'ont tourné qu'avec un **stub `sounddevice`** (PortAudio absent) — identique sur la copie d'origine : 12/12.
4. **S8 partiel.** Le contrat structuré est adopté par les outils de contrôle PC, Hermes et fichiers, **pas** par les ~80 autres outils ; `jarvis14._executer_outils` transmet toujours du texte au LLM (l'honnêteté passe par le message, pas par un champ typé). Pas de reprise après échec (arrêt propre seulement), pas de planificateur multi‑étapes générique. Le test « recherche → rédaction → ouverture d'un document » de bout en bout **n'a pas été exécuté**.
5. **S6 partiel** : les paraphrases sont testées sur le routage déterministe, **pas** avec un vrai LLM (aucune clé, aucun réseau ici). La confusion `noter`/`taper_texte` côté LLM est traitée à la source (catalogue d'outils + descriptions + prompt) mais pas mesurée.
6. **S10 partiel** : scénarios hors ligne et erreurs navigateur partiellement couverts par mocks ; la recette finale réelle est dans `valider_windows.py`.
7. **Astra** : appels vision réels non testés ; la vérification finale ajoute un appel LLM par tâche (désactivable).
8. **Points connexes du plan (§15)** — Mistral 429, ElevenLabs 401, Hue, placeholders, calibration micro : **non investigués** (aucune clé/réseau/matériel ici). Rien n'a été modifié à leur sujet, hors la lecture du code de repli Mistral/Gemini (R1/R2).
9. Changement de comportement à connaître : les messages « X lancé. » sont devenus « X est ouvert. » / « J'ai lancé X, mais je ne vois pas sa fenêtre… » selon ce qui est constaté ; une chaîne s'arrête à la première étape en échec.
10. `choisir_fenetre` (ancienne fonction) est conservée car testée, mais n'est plus utilisée par `_activer`.

## 7. Verdict par section

| ID | Sujet | Statut |
|---|---|---|
| S1 | Diagnostic Windows / UI Automation | **Corrigé mais non vérifiable sur cet environnement** |
| S2 | Souris et clavier | **Corrigé mais non vérifiable** (routage et logique : testés) |
| S3 | Chrome et Playwright | **Corrigé et testé** (diagnostic réel sur Linux) · cause racine Windows : **non établie** |
| S4 | Astra | **Corrigé et testé** (mocks) · vision réelle non testée |
| S5 | Fichiers et applications | Fichiers : **corrigé et testé** · applications : non vérifiable |
| S6 | Routage vocal | **Partiellement corrigé** (déterministe testé, LLM non mesuré) |
| S7 | Hermes | **Corrigé et testé** (mocks, pas d'Hermes réel) |
| S8 | Orchestration | **Partiellement corrigé** |
| S9 | Auto-modification | **Corrigé et testé** (git réel) · non branché à la voix |
| S10 | Recette finale | **Partiellement corrigé** — script fourni, exécution Windows à faire |

## 8. Fichiers modifiés / ajoutés

Modifiés (21) : `core/cloud.py`, `core/contexte.py`, `core/playwright_partage.py`, `core/registre.py` (+1 ligne N3), `core/routage_intentions.py`, `jarvis14.py` (prompt), `tools/apps.py`, `tools/astra_pc.py`, `tools/controle_pc.py`, `tools/deleguer_a_hermes.py`, `tools/navigateur.py`, `tools/notes.py` (description), `tools/souris.py`, `tools/systeme.py`, `scripts/diagnostic_pc.py`, `config.example.yaml`, `CHANGELOG.md`, `tests/test_astra_pc.py`, `tests/test_media_routing.py`, `tests/test_transcription.py`, `tests/test_web_routing.py`.
Ajoutés (8) : `core/resultat.py`, `core/auto_modification.py`, `tools/fichiers.py`, `scripts/auto_modif.py`, `scripts/valider_windows.py`, `tests/test_pc_fiabilite.py`, `tests/test_regressions_s3_s4_s7_s9.py`, `tests/test_fichiers.py`.
Annulation : `corrections.patch` (diff unifié complet, applicable en sens inverse avec `patch -R`) ; l'état initial reste dans `.git` (aucun commit n'a été fait).

Modifications de tests existants (toutes justifiées, aucune supprimée) : `startfile` patché avec `create=True` (portabilité hors Windows) ; stub de `faster_whisper` quand le paquet optionnel est absent ; `test_utilitaire_windows_reste_une_application` et `test_boucle_utilise_astra…` adaptés au nouveau contrat (« lancé » ≠ « ouvert » ; vérification finale Astra par défaut) avec nouveaux tests couvrant le cas actif.
