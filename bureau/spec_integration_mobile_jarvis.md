# Spécification Technique : Intégration Mobile de Jarvis

## 1. Objectif
Étendre les fonctionnalités de Jarvis du poste PC principal vers un terminal mobile (smartphone) afin de permettre un contrôle vocal distant, l'affichage de l'overlay et l'exécution d'actions spécifiques au mobile via l'architecture existante.

## 2. Architecture Technique Cible
- **Serveur Central (PC Principal) :** Enrichissement de `core/serveur.py` pour supporter un canal WebSocket bidirectionnel sécurisé (authentification par token pré-partagé).
- **Client Mobile (Application ou PWA) :** Capture audio (wake-word / push-to-talk), restitution audio (TTS) et affichage synchrone des réponses de Jarvis.
- **Nouveaux Outils (`tools/mobile.py`) :** Exposition de commandes spécifiques au mobile (notifications, géolocalisation, statut batterie, contrôle d'applications mobiles).

## 3. Plan d'Implémentation pour Claude
1. **Sécurisation du Pont Réseau :** Étendre `core/serveur.py` et `core/pont_iphone.py` pour gérer l'enregistrement des clients mobiles connectés.
2. **Création du Module d'Outils Mobiles :** Implémenter `tools/mobile.py` en s'inspirant des outils de `tools/astra_pc.py` et `tools/systeme.py`.
3. **Mise en place du Client Léger :** Définir les endpoints HTTP/WebSocket consommables par une application externe (Flutter ou PWA).
4. **Validation et Tests :** Rédiger les tests unitaires associés dans `tests/test_poste_distant.py`.
