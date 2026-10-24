# Changelog

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
