# Changelog

Toutes les évolutions notables de Jarvis. Format inspiré de
[Keep a Changelog](https://keepachangelog.com/fr/) ; versionnage
[SemVer](https://semver.org/lang/fr/).

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
