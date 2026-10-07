# Contexte portable du projet Jarvis

Ce document peut être fourni à une IA pour lui donner rapidement le contexte du
projet. Il est volontairement général : il ne contient aucune clé, aucun token,
aucune adresse privée ni aucun chemin propre à une installation.

## Résumé

Jarvis est un assistant vocal francophone, extensible et principalement local. Il
tourne sur un PC Windows et peut recevoir la voix depuis plusieurs pièces grâce à
des satellites Raspberry Pi. Il utilise une transcription locale, un LLM au choix
(local ou cloud), une synthèse vocale configurable et un registre d'outils pour agir
sur le PC, le web et la maison.

La doctrine d'architecture est : **« Hermes orchestre et pense ; Jarvis détient les
clés et le corps. »** Hermes prend en charge les recherches, analyses et productions
longues. Jarvis conserve les identifiants, les confirmations, la voix, les micros,
la caméra, la domotique et toutes les actions réelles.

## Architecture

- **Jarvis principal** : processus Python sur Windows, dialogue vocal, outils,
  confirmations et orchestration temps réel.
- **Satellites de pièce** : Raspberry Pi avec micro/haut-parleur. Le mot
  d'activation est détecté localement, puis l'audio de la demande est envoyé au PC
  sur le réseau local par WebSocket authentifié.
- **LLM** : fournisseur sélectionnable (OpenAI, Anthropic/Claude ou Ollama local).
- **Hermes** : agent de fond local, appelé pour les analyses, recherches et travaux
  de création de contenu. Il lit les ressources autorisées et écrit uniquement des
  brouillons dans son périmètre.
- **Interface** : HUD vocal, overlay de réponses et panneau de configuration local.
- **Outils** : catalogue Python extensible avec métadonnées, niveau de sécurité,
  confirmation éventuelle et exposition MCP explicitement contrôlée.

## Fonctions déjà présentes

- mot d'activation « Hey Jarvis », conversation suivie temporaire et ordre vocal de
  retour en veille ;
- transcription locale et réponses vocales avec moteur configurable ;
- contrôle d'applications, navigateur, écran, médias et tâches PC ;
- mode opérateur Astra pour les tâches visuelles multi-étapes sur le PC, toujours
  avec confirmation locale avant prise de contrôle ;
- domotique via Alexa/routines, plus certains appareils locaux pilotés directement ;
- contrôle par gestes de la main avec webcam, entièrement local : calibration,
  mode Fenêtres, mode Audio, swipes et garde-fous contre les faux positifs ;
- satellites audio multi-pièces avec arbitrage du micro le plus proche ;
- agenda, météo, mails, notes, appels, musique, suivi de contenus et outils web ;
- Hub de contenu avec inspirations, scripts et brouillons ;
- délégation automatique à Hermes pour écrire/améliorer un script, proposer des
  hooks ou idées vidéo et analyser des inspirations ;
- suivi des coûts, modes local/hybride/qualité et bascule locale en cas de plafond ;
- serveur MCP borné, pont mobile et interfaces locales.

## Comportement vocal attendu

- Une demande simple reçoit une réponse directe : aucune phrase de remplissage pour
  « Comment ça va ? » ou « Quelle heure est-il ? ».
- Une tâche réellement lente reçoit un accusé court et contextuel pendant son
  exécution : « Je regarde tes mails », « Je cherche une recette », etc.
- Après une réponse, une courte fenêtre permet d'enchaîner sans répéter le mot
  d'activation. « Mets-toi en veille » ferme immédiatement cette fenêtre.
- En veille, seule l'expression complète « Hey Jarvis » doit réveiller le satellite.
- Les demandes explicites de création de contenu vont à Hermes ; une simple mention
  d'une vidéo ou l'état d'avancement d'un contenu reste chez Jarvis.

## Sécurité et confidentialité

- Le dépôt est public : ne jamais y écrire de secret, token OAuth, cookie, adresse
  privée, inventaire personnel, journal, donnée financière ou chemin local.
- Les identifiants restent dans le fichier de configuration local gitignoré, côté
  Jarvis. Ils ne sont jamais transmis à Hermes.
- **N1** : lecture/action sûre ; **N2** : action locale réversible pouvant demander
  une confirmation ; **N3** : effet significatif, confirmation vocale locale à
  chaque fois, sans autorisation permanente.
- Micro, caméra, gestes, Alexa, lumières et données financières ne sont jamais
  exposés à Hermes ou à MCP par commodité.
- Les images de la webcam des gestes ne sont ni stockées ni envoyées : seul un label
  de geste quitte le processus local de suivi.

## Principes pour modifier le projet

1. Inspecter l'existant avant de coder et préserver les changements non liés.
2. Préférer un routage déterministe pour les intentions à risque de confusion, mais
   exiger un ordre explicite afin qu'une conversation ordinaire ne déclenche rien.
3. Garder Jarvis réactif ; envoyer les travaux longs à Hermes en arrière-plan.
4. Ne jamais élargir les droits d'Hermes ou d'un accès distant pour simplifier une
   fonctionnalité.
5. Ajouter des tests pour les formulations positives et les contre-exemples.
6. Scanner chaque diff avant publication du dépôt.

## État et prochaines étapes générales

Le socle vocal, les satellites, les gestes, la domotique, le HUD, la sécurité, le
routage LLM et Hermes sont opérationnels. Les validations réelles et réglages fins
restent importants : sensibilité du mot d'activation selon la pièce, fluidité des
accusés vocaux, calibration des gestes, connexions OAuth et tests matériels. Les
extensions futures peuvent inclure un inventaire domestique visuel, davantage de
données dans le cockpit, l'énergie locale et de nouveaux satellites.

Quand une IA reçoit ce document, elle doit traiter les demandes de l'utilisatrice
comme des étapes ciblées, et non comme une autorisation d'implémenter toute la feuille
de route en une seule fois.
