# Guide — Jarvis Security Intelligence

Audit de sécurité **autorisé** de laboratoires, applications locales et de votre propre code. Tout ce qui est décrit ici existe dans le code
(aucune commande inventée). Les commandes vocales ne fonctionnent que lorsque **Ghost Protocol est actif**.

## 1. Avant de commencer

1. Installer Jarvis comme d'habitude (`uv sync`). Facultatif — outils externes (chacun est détecté tout seul ; sinon l'agent natif équivalent est utilisé ou la limite est indiquée) :
   nmap, nuclei (+ `nuclei-templates`, variable `JARVIS_SEC_NUCLEI_TEMPLATES`), semgrep, gitleaks, trivy, OWASP ZAP, OWASP Dependency-Check.
   Burp Suite Community **n'est pas intégrable** (aucune API) : à utiliser à la main.
2. Vérifier ce qui est réellement opérationnel : `python scripts/security_audit.py outils`
   (états : `operationnel`, `absent`, `present_en_erreur`, `non_integrable`).
3. **Enregistrer la cible** (jamais à la voix) :

```powershell
python scripts/security_cible.py add http://127.0.0.1:3000 --attestation "OWASP Juice Shop lance par moi sur mon PC" --duree-h 8
python scripts/security_cible.py code C:\chemin\vers\mon\projet
python scripts/security_cible.py list
python scripts/security_cible.py revoke 127.0.0.1
```
   * `127.0.0.1`/`localhost` : accepté tel quel ; IP privée (VPN) ou instance PortSwigger : attestation ≥ 15 caractères ; hôte externe : attestation ≥ 40 caractères + `--proprietaire`.
   * L'enregistrement expire (24 h par défaut, 30 jours max) et se révoque. `--actions` limite les catégories (`web api reseau outils`).
   * Les domaines des plateformes (tryhackme.com, hackthebox.com, portswigger.net, pentesterlab.com, owasp.org…) sont **refusés** : on enregistre l'adresse de *votre* machine/instance.

## 2. Commandes vocales (Ghost actif)

Dites d'abord « active le mode hacker » / « Ghost Protocol ».

| Phrase (exemples) | Effet |
|---|---|
| « prépare un audit de sécurité » | Explique la marche à suivre (ne lance rien) ; avec une adresse, prépare la cible |
| « analyse ce laboratoire http://127.0.0.1:3000 » (ou « … 127 point 0 point 0 point 1 port 3000 », « … juice shop ») | Vérifie le périmètre ; **si la cible est enregistrée**, lance l'audit complet (passif, limité). Sinon refuse et explique pourquoi |
| « commence la reconnaissance autorisée » | Étape de reconnaissance seule |
| « analyse les vulnérabilités de cette application » | Reconnaissance + analyses (web/API/réseau/outils), sans validation ni rapport |
| « vérifie les résultats détectés » | Validation indépendante + corrélation |
| « génère le rapport de sécurité » | Rapport JSON + HTML (+ PDF si Chromium/Playwright dispo) |
| « état de l'audit » | Résumé oral (confirmés / à vérifier / total) |
| « arrête l'audit » (ou « arrêt d'urgence audit ») | Arrêt d'urgence : requêtes refusées, outils tués |

Les quatre étapes partielles réutilisent la cible de la dernière commande « analyse ce laboratoire ». Les adresses dictées : « a point b point c point d [port N] » ou « localhost port N ».
Sur le HUD : panneau **SECURITY INTELLIGENCE** (état, cible, étape, agents/outils actifs, compteurs, derniers constats) et bouton **EMERGENCY STOP**.

En ligne de commande (mêmes moteurs) : `python scripts/security_audit.py run http://127.0.0.1:3000` ou `run --code C:\mon\projet`.
Rapports : `logs/security/audits/<id>/rapport.{json,html,pdf}` ; journal des actions : `journal.jsonl` ; session reprenable : `session.json`.

## 3. Pas-à-pas par plateforme

> Respectez toujours les règles de la plateforme. Jarvis n'envoie que des requêtes en lecture seule, sans connexion ni exploitation : il ne **résout pas** les exercices ; il inventorie surfaces, expositions et mauvaises configurations.

**OWASP Juice Shop (local, recommandé pour démarrer)** : lancez Juice Shop sur votre PC (`npm start` ou Docker, port 3000) → `security_cible.py add http://127.0.0.1:3000 --attestation "Juice Shop lancé par moi"` → « active le mode hacker » → « analyse ce laboratoire juice shop ».
Mesuré sur Juice Shop 20.3.0 (agents natifs) : CSP absente, métriques Prometheus exposées, `/api/Feedbacks` lisible sans authentification, répertoire `/ftp` listable, CORS permissif, traces d'erreur détaillées.

**TryHackMe** : démarrez la machine, connectez-vous au VPN/AttackBox, notez l'IP de la machine (ex. 10.x.x.x). `add http://<IP>:<port> --attestation "Machine THM démarrée par moi via mon VPN, room …"`. Jamais `tryhackme.com`. Ajoutez `--ports` pour chaque port web.

**Hack The Box** : même principe avec l'IP de la machine (VPN actif). Jamais `hackthebox.com` / `app.hackthebox.com`. Respectez les règles de la plateforme sur les outils automatisés.

**PortSwigger Web Security Academy** : démarrez le lab ; enregistrez l'URL de l'instance (`https://<id>.web-security-academy.net`) avec une attestation. Jamais `portswigger.net`. Vérifiez les conditions d'usage des scans automatisés avant de lancer.

**PentesterLab** : démarrez l'exercice ; enregistrez l'URL/IP de *votre* instance. Jamais `pentesterlab.com`.

**Votre propre code** : `security_cible.py code <dossier>` puis `security_audit.py run --code <dossier>` : secrets (gitleaks si présent, sinon natif), dépendances (OSV — envoie uniquement noms/versions), règles de mauvaises pratiques, trivy/semgrep/dependency-check s'ils sont opérationnels.

## 4. Lire un rapport

12 sections : résumé exécutif, périmètre autorisé, environnement testé, méthodologie et décisions du moteur, outils utilisés et versions, vulnérabilités **confirmées**, vulnérabilités **reproduites** (impact non démontré), résultats **non vérifiés**, faux positifs écartés, corrélations, recommandations, limites — puis une conclusion. Statuts : POTENTIEL, À VÉRIFIER, REPRODUIT, CONFIRMÉ, NON CONCLUANT, FAUX POSITIF PROBABLE. « Confirmé » = ré-observé de façon indépendante ; une détection d'outil non ré-observée n'est jamais présentée comme confirmée. La section « limites » liste ce qui n'a pas été testé (authentification, IDOR, logique métier…) et les outils absents.

## 5. Dépannage

* « cible non enregistrée » : `security_cible.py list` ; la cible a peut-être expiré (reconduire) ou le port diffère.
* « HORS PERIMETRE / rebinding » : l'IP du nom d'hôte a changé depuis l'enregistrement → ré-enregistrer après vérification.
* nuclei « arrêté par délai » : normal sur machine modeste (5 min max) ; les résultats partiels sont gardés et signalés.
* Pas de PDF : installer Chromium (`uv run playwright install chromium`) ; JSON/HTML restent produits.
* Pas de réponse du LLM : sans effet, l'audit est déterministe (`conseiller_llm: false` pour le désactiver).
