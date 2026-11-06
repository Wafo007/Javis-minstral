# GHOST PROTOCOL

Mode tactique cinématographique de Jarvis. **Tout est une simulation** : aucun scan réseau, aucune intrusion, aucun accès appareil.
Le mode est réversible : « Désactive le mode hacker » rend à Jarvis exactement son comportement normal (HUD, voix, personnalité).

## Fonctionnement

| | Mode normal | Mode Ghost |
|---|---|---|
| HUD | bleu/cyan habituel | rouge `#050505 / #ff1744 / #800000`, radar simulé, panneau mission, terminal, scanlines |
| Voix | voix habituelle (`tts.moteur`) | ElevenLabs, repli Windows automatique |
| Personnalité | habituelle | tactique, sûre d'elle, un peu provocatrice, répond toujours normalement aux questions techniques |
| Au redémarrage | — | toujours inactif |

Activation et désactivation sont **locales** (pas de LLM, pas d'Internet) : elles fonctionnent même si le fournisseur LLM est en panne.

## Commandes vocales

Utilise le STT existant (aucun second système de reconnaissance). Accents et ponctuation ignorés.

- Activer : « Active le mode hacker », « Active Ghost Protocol », « Active le protocole Ghost ».
- Désactiver : « Désactive le mode hacker », « Quitte Ghost Protocol ». La phrase d'adieu est dite avec la voix Ghost, puis le mode se ferme.
- GHOST RECON : « Lance Ghost Recon », « Analyse cette cible », « Analyse cette adresse e-mail jean@exemple.com » (adresse écrite ou dictée « jean arobase gmail point com »).
- GHOST INTELLIGENCE : « Lance Ghost Intelligence », « Lance une analyse complète ».
- GHOST ATTACK : « Prépare une simulation d'intrusion », « Lance Ghost Attack ».
- Divers : « Arrête la simulation », « Lance la simulation » (exécute le script prêt), « Coupe la voix Ghost » / « Rétablis la voix Ghost » (économie de quota), « Statut voix Ghost ».

Les formulations génériques (« analyse cette cible »…) ne sont captées que Ghost actif ; hors mode, la phrase suit le routage normal.
Les noms explicites (« lance Ghost Recon ») répondent toujours, par un rappel d'activation si le mode est inactif.

## Architecture (`modes/ghost_protocol/`)

`controller.py` (activation, scénarios, exécution du script) · `commandes.py` (voix) · `state_manager.py` (état + écouteurs) ·
`simulation_engine.py` (thread de scénario) · `scenarios.py` · `responses.py` (dialogues sans LLM) · `personality.py` (consigne ajoutée au prompt système) ·
`fake_intelligence.py` (rapports étiquetés RÉEL/SIMULÉ) · `fake_code_generator.py` (script de démonstration + audit AST) ·
`voice_manager.py` (choix de la voix) · `elevenlabs_provider.py` (API, cache, disjoncteur) · `audio_cache.py` · `config.py` · `hud_bridge.py` (SSE).

Points d'accroche dans l'existant : `core/tts.py` (`tts()` renvoie le provider Ghost tant que le mode est actif, sinon comportement inchangé),
`core/commandes_locales.py` (commandes Ghost en tête), `jarvis14.py` (verrou de parole : une seule synthèse à la fois ; finalisation de la sortie après
l'adieu ; consigne de personnalité ajoutée au prompt tant que Ghost est actif), `hud.py`/`hud.html` (événements `ghost*` sur le flux SSE `/flux`, rejoués aux clients tardifs).
Le routeur multi-LLM n'est pas dupliqué : la personnalité n'est qu'un ajout au prompt du tour.

## Configurer ElevenLabs

1. Créez un compte sur elevenlabs.io, puis une clé API (Developers → API Keys).
2. Choisissez une voix (Voices) et copiez son *Voice ID*. Pour le style demandé (grave, posé, cinématographique), choisissez une voix masculine grave ; le choix reste le vôtre.
3. Copiez `.env.example` en `.env` (jamais versionné) et remplissez `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, éventuellement `ELEVENLABS_MODEL_ID` (défaut `eleven_flash_v2_5`, économe).
   Ordre de lecture : variable d'environnement > `.env` > bloc `ghost_protocol.elevenlabs` / `elevenlabs` de `config.yaml`.
4. Ne collez jamais la clé dans un chat. Elle n'est ni journalisée, ni envoyée à un LLM, ni écrite dans le code.

Réglages de voix (stabilité 0,55, similarité 0,8, style 0,35, vitesse 0,92) dans `config.py`. Requête : `POST /v1/text-to-speech/{voice_id}`, en-tête `xi-api-key`.

### Voix en mode normal
Le mode Ghost n'appelle jamais ElevenLabs hors mode. **Mais** si votre `config.yaml` a `tts.moteur: auto` en mode cloud, Jarvis utilise *déjà*
ElevenLabs en mode normal (comportement antérieur, conservé volontairement). Pour la voix Windows en normal : `tts.moteur: windows`.

## Limites du plan gratuit et économie
- Le quota réel dépend de votre compte et change : **vérifiez-le sur le tableau de bord ElevenLabs**. Ce projet n'affirme aucune durée.
- Économies : cache disque (une phrase n'est jamais générée deux fois), messages techniques/très courts non vocalisés, longueur parlée limitée (`max_caracteres`, 220),
  phrases de scénario courtes, voix Ghost coupable (« coupe la voix Ghost »), compteur local de caractères (`logs/ghost/usage.json`), plafond local optionnel `quota_mensuel`.
- Les formats exacts des erreurs 401/429/quota ne figurent pas sur la page de documentation consultée : la classification (clé invalide / quota / réseau) est une
  heuristique sur le code HTTP et le texte, **non validée contre la vraie API**.

## Repli
ElevenLabs indisponible (clé absente/invalide, quota, réseau, timeout, audio illisible) : l'erreur est journalisée (sans la clé), la voix Windows prend le relais,
le HUD affiche discrètement `GHOST VOICE : FALLBACK`, puis un disjoncteur retente automatiquement (clé invalide 1 h, quota 30 min, réseau 45 s doublant jusqu'à 10 min,
génération 2 min). Une nouvelle clé est testée immédiatement. Au retour, la voix Ghost revient seule.

## Scénarios
- **GHOST RECON** : analyse *réelle* du format de l'adresse et du domaine (locale, hors ligne). Identité : `UNVERIFIED`. IP et menace : *simulées* (IP des plages de documentation 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24).
  Chaque ligne est étiquetée `[REAL]` ou `[SIMULATED]`. Aucune recherche réseau.
- **GHOST INTELLIGENCE** : INITIALIZING INTELLIGENCE ENGINE → LOADING VIRTUAL DATABASE → ANALYZING SIMULATED INDICATORS → GENERATING THREAT ASSESSMENT → PREPARING FINAL REPORT. La progression = étapes réellement terminées.
- **GHOST ATTACK** : génère `logs/ghost/ghost_attack_simulation.py` (≈220 lignes, fictif). Il est audité par analyse AST (imports en liste blanche, aucun appel réseau/processus/fichier/eval), ré-audité avant exécution, et le bouton **RUN SIMULATION**
  l'exécute dans un sous-processus isolé (`-I`, environnement assaini, crochet d'audit bloquant sockets/sous-processus/écriture, délai 60 s). Il se termine par le bloc `GHOST ATTACK SIMULATION … RESULT : SUCCESS`.

## Tests
`uv run pytest tests/test_ghost_protocol.py -q` couvre : activation, désactivation, activation répétée, retour à l'état normal, voix normale sans appel ElevenLabs, voix Ghost, clé absente/invalide, quota, repli et récupération,
pas de double lecture (vérification structurelle), SSE, génération du script, absence de connexion (audit + exécution réelle sous garde), sans Internet, sans LLM, compatibilité.
**Le transport ElevenLabs est un double** : aucune génération audio réelle n'est testée.

## Désactiver / dépanner
- Commande : « Désactive le mode hacker » ; bouton EXIT GHOST du HUD ; redémarrer Jarvis (le mode ne persiste jamais).
- Pour supprimer la voix Ghost : ne définissez pas la clé (Ghost reste utilisable en voix Windows).

## Problèmes connus
- Aucune voix ElevenLabs réelle n'a été testée (pas de clé disponible pendant le développement).
- Jarvis complet non lancé sous Windows pendant le développement ; HUD vérifié seulement dans Chromium (Linux).
- La sortie vocale en cours de phrase n'est pas coupée par le mode ; l'adieu est toujours dit en entier avant la bascule.
- Deux tests préexistants de `tests/test_mobile.py` échouent déjà sur l'archive d'origine (ordre de routage), indépendamment de Ghost.
