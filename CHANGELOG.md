# Changelog

## GHOST PROTOCOL (novembre 2026)

- Nouveau mode reversible `modes/ghost_protocol/` : « active le mode hacker » -> HUD rouge tactique (reacteur, radar simule, panneau
  de mission, terminal), personnalite tactique, voix ElevenLabs (repli Windows automatique), scenarios GHOST RECON / INTELLIGENCE /
  ATTACK 100 % simules. « Desactive le mode hacker » restaure l'etat normal. Documentation : `docs/GHOST_PROTOCOL.md`.
- Points d'accroche minimaux : `core/tts.py`, `core/commandes_locales.py`, `jarvis14.py` (verrou de parole, finalisation de sortie,
  consigne de personnalite), `hud.py`/`hud.html` (canal `ghost*` du flux SSE), `config.example.yaml`, `.env.example`.
- Tests : `tests/test_ghost_protocol.py` (transport ElevenLabs double : aucune voix reelle validee par les tests).

## Controle d'un telephone Android par ADB (novembre 2026)

- `core/mobile_adb.py` + `tools/mobile.py` : lancer une app, statut, media, touches, defilement, notification, lien (N1) ; toucher/taper,
  lire/capturer l'ecran, notifications, position, photo (N2). Routage « ... sur mon telephone » avant l'ouverture d'app du PC.
- `scripts/mobile_appairer.py`, bloc `mobile:` de `config.example.yaml`, guide `docs/mobile_android.md`, tests `tests/test_mobile.py`.

## Missions autonomes d'auto-amelioration (octobre 2026)

- Nouveau moteur de missions (`core/missions.py`, `core/mission_agent.py`, `core/fournisseurs_mission.py`, `core/mission_rapport.py`,
  `scripts/mission_worker.py`, `tools/missions.py`) : « ameliore ton routage, tu disposes de 60 minutes » -> worker detache, workspace
  `git worktree` isole, vrais tests, comparaison a la baseline, rapport en 17 sections, notification. Voir `docs/MISSIONS_AUTONOMES.md`.
- `core/auto_modification.py` etendu (worktree, checkpoint, integration sur autorisation) ; modules du moteur proteges contre l'auto-modification.
- `core/registre.py` : `mission_integrer` (N3). `core/routage_intentions.py` : `router_mission` en tete des routes deterministes.
- `jarvis14.py` : reprise des missions interrompues au demarrage + annonce vocale de fin. `config.example.yaml` : bloc `missions:`.
- Tests : `tests/test_missions.py` (scenarios A-H).

## Corrections du journal reel (octobre 2026)

- `core/cdp_leger.py` : pilotage de Chrome par CDP sans Playwright (ni greenlet, ni Visual C++) ; `navigateur._tenter_cdp` y bascule seul.
- `tools/youtube.py` (`youtube_lire`) : lance une video sans cliquer ; routage « lance X sur YouTube ».
- Navigation envoyee a Hermes, « clique dessus » pris pour un bouton, mode travail declenche par une longue dictee : corriges.
- Personnalite par defaut chaleureuse (blagues, reponses detaillees, recommandation finale) ; « mode normal » n'est plus la personnalite neutre.
- `tools/mon_code.py` : `code_modifier` (sauvegarde + verification de syntaxe + restauration), `code_tester`, cycle git `code_modification_*`.
- `cloud.secours_actif()` : secours Gemini coherent entre chat et vision (Astra) ; `astra_pc.sans_confirmation` (opt-in, voix locale).
- Limites de tour 240 s / 10 tours / 20 appels, duree d'une phrase 60 s, Astra 15 etapes (config.example.yaml).
- `scripts/reparer_vcruntime.py` : DLL Visual C++ en local si le redistribuable ne s'installe pas.

Toutes les évolutions notables de Jarvis. Format inspiré de
[Keep a Changelog](https://keepachangelog.com/fr/) ; versionnage
[SemVer](https://semver.org/lang/fr/).

## [Non publié] — 2026-10 · Audit et correction du contrôle du PC

Voir `RAPPORT_AUDIT.md` pour le détail, les preuves et les limites de validation.

### Corrigé
- `core/cloud.py` : `UnboundLocalError` dans `decider_action_vision` (OpenAI/Anthropic plantaient avant
  tout appel ; boucle Mistral référençant `e` hors de son `except`) — régression du commit « gemini vision ».
- Routage : « Bloc-notes » déclenchait le domaine `notes` (le LLM ne voyait que `noter`) ; un « Jarvis, »
  en tête cassait les commandes enchaînées ; la ponctuation du texte dicté était perdue.
- `tools/controle_pc.py` : focus vérifié (plus de faux « au premier plan »), lancement vérifié (plus de
  faux « est ouvert »), `Get-StartApps` vide plus mis en cache, secours par exécutables intégrés / App Paths,
  saisie `SendInput` contrôlée (emoji, échec remonté), relecture UI Automation du texte tapé, coordonnées
  UIA en pixels physiques (DPI), clic précédé d'une preuve de position du curseur.
- Astra : vérification finale, détection d'écran inchangé, arrêt après échecs répétés.
- Hermes : une réponse vide n'est plus « terminée » ; livrable vérifiable ; statut « partielle ».
- Playwright : diagnostic de la chaîne complète (greenlet, sync_api, moteur, Chromium) et message clair
  si l'API synchrone est appelée depuis un autre thread.

### Ajouté
- `core/resultat.py` (résultat structuré : succès / vérifié / détails / erreur, compatible `str`).
- `tools/fichiers.py` (fichiers confinés, atomiques, suppression en corbeille N3).
- `core/auto_modification.py` + `scripts/auto_modif.py` (branche dédiée, diff, tests, retour arrière).
- `scripts/valider_windows.py` (validation réelle sur Windows).
- Tests : `test_pc_fiabilite.py`, `test_regressions_s3_s4_s7_s9.py`, `test_fichiers.py`.

## [1.0.0] — 2026-08-07

Première version publique. Assistant vocal local en français, architecture
modulaire, deux modes (cloud / local hors ligne).

### Cœur
- Chaîne vocale : openWakeWord (« Hey Jarvis ») → faster-whisper (STT local) →
  LLM → synthèse vocale, avec fenêtre de suivi pour enchaîner sans redire le mot-clé.
- Architecture modulaire : chaque outil est un fichier de `tools/` auto-découvert
  (décorateur `@outil`), registre central, `config.yaml` unique non versionné.
- Confirmation vocale des actions irréversibles ; interruption « attends/stop »
  (barge-in anti-écho) ; accusé de réception immédiat pour les outils lents.
- Abstraction des providers (mode `cloud` | `local`) :
  - LLM : **Claude** (Anthropic) ou **Ollama** (`qwen3.5:4b`…), même interface.
  - TTS : **ElevenLabs** ou, en local, **Piper** / **Kokoro** (repli voix Windows).
  - STT : faster-whisper (local dans les deux modes, GPU si dispo).

### Outils
- Domotique : Philips Hue (allumer, luminosité, couleur), ambiances/scènes.
- PC & streaming : OBS (direct, enregistrement, scènes, replay), stats système,
  lancement d'apps, média/volume, capture d'écran (vision).
- Productivité : Google Agenda (tous les agendas, y compris iCal abonnés),
  Gmail, brief du matin, mémoire long terme, minuteurs, météo, personnalités.
- Présence : détection par ping du téléphone, modes automatiques.
- Web : recherche, réservation pilotée par LLM (Playwright), assistance sur le
  vrai Chrome (CDP) avec domaines protégés en lecture seule.
- Communication : Discord (mentions + messages du jour), Instagram (abonnés &
  vues vs la veille, multi-comptes, refresh auto des tokens), appels Twilio
  (message simple V1, conversation temps réel V2).
- Serveur MCP : expose les outils domotique/PC à tout client MCP (Claude Desktop,
  Hermes), liste blanche par outil.

### Confidentialité & sécurité
- Secrets et données perso jamais versionnés (config, mémoire, logs, transcriptions
  d'appels, tokens OAuth, profils navigateur).
- Appels téléphoniques : présentation honnête comme assistant automatisé ; jamais
  de données bancaires ni de mots de passe ; blocage des numéros surtaxés.

### Installation
- Installateur interactif `scripts/setup.py` et diagnostic `scripts/doctor.py`.
- `INSTALL_WITH_AI.md` (FR/EN) : guide agnostique pour installer via n'importe
  quelle IA gratuite.
- Documentation par intégration dans `docs/`, README FR (défaut) + EN.

[1.0.0]: https://github.com/sosoj92/jarvis-assistant-vocal/releases/tag/v1.0.0
