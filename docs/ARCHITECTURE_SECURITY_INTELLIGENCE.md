# Architecture — Jarvis Autonomous Security Intelligence

Plateforme d'**audit de sécurité autorisé** (laboratoires, applications locales, code dont vous êtes propriétaire) intégrée à Ghost Protocol.
Principe directeur : *une fonctionnalité réellement opérationnelle vaut mieux que dix fonctionnelles fictives.* Aucune détection n'est simulée ;
quand une capacité n'existe pas, le rapport le dit.

## 1. Vue d'ensemble

```
Voix ─► commandes.py ─► commandes_securite.py ─┐
HUD (bouton arrêt) ─► hud.py ──────────────────┤
CLI scripts/security_*.py ─────────────────────┴─► security/__init__.Service ─► audit.Audit (orchestrateur)
                                                         │  boucle déterministe : decision.suivante()
                       ┌─────────────────────────────────┼─────────────────────────────────────────┐
               agent_recon  agent_web  agent_api  agent_reseau  agent_code   outils.py (nmap/nuclei/ZAP/semgrep/gitleaks/trivy/dep-check)
                       └──────────────► Contexte (cible, Garde, ClientCadre, résultats, faits, limites) ◄───────┘
                                                         │
                              agent_validation (ré-observation indépendante) ─► agent_vuln (corrélation, score)
                                                         │
                                                  rapport.py  → JSON / HTML / PDF
                                  hud_bridge.securite() ─► SSE `ghost_secu` ─► panneau « SECURITY INTELLIGENCE »
```

## 2. Les 8 agents

| Agent | Fichier | Rôle réel |
|---|---|---|
| RECON | `agent_recon.py` | Exploration (BFS borné), formulaires, scripts, endpoints extraits du JS, `robots.txt`, technologies |
| WEB | `agent_web.py` | En-têtes, cookies, CORS, chemins sensibles (signatures de contenu + référence « page inexistante » anti-SPA), réflexion d'un *canari* inerte, sonde SQL différentielle, traces d'erreur |
| API | `agent_api.py` | Endpoints GET sans authentification, méthodes annoncées (OPTIONS), erreurs 500 |
| RÉSEAU | `agent_reseau.py` + nmap | Scan TCP *connect* natif (ports courants, bannières), TLS (version négociée, TLS 1.0/1.1) ; nmap si opérationnel |
| CODE | `agent_code.py` + gitleaks/semgrep/trivy/dep-check | Secrets (motifs + entropie, **valeurs jamais stockées**), règles de mauvaises pratiques, dépendances via OSV (noms/versions seulement) |
| VULNÉRABILITÉS | `agent_vuln.py` | Mapping CWE, élévation de gravité motivée, contradictions, score 0–100 |
| VALIDATION | `agent_validation.py` | Ré-observe chaque constat **indépendamment** ; promeut/rétrograde le statut |
| REPORTING | `rapport.py` | Rapport 12 sections, réel vs non vérifié séparés |

## 3. Garde-fous (un seul point de contrôle : `Garde.autoriser`)

Chaque requête réseau, chaque exécution d'outil, chaque lookup OSV passe par la garde, qui journalise (JSONL, secrets masqués) et refuse :
arrêt d'urgence actif · cible expirée/révoquée · action hors liste blanche · méthode ≠ GET/HEAD/OPTIONS · hôte ou port hors périmètre ·
catégorie non accordée · **IP changée depuis l'enregistrement (anti DNS-rebinding)** · budget de requêtes dépassé · débit (token-spacing).
Les redirections sont suivies à la main et **re-validées à chaque saut** ; une redirection vers l'extérieur est refusée sans interrompre l'étape.

Registre de cibles (`perimetre.py`) : enregistrement explicite, daté, avec attestation :
* `local` (127.x / localhost) : accepté ; `reseau_prive` (IP VPN HTB/THM…) et `lab_portswigger` (`*.web-security-academy.net`) : attestation ≥ 15 caractères ;
* `externe` : attestation ≥ 40 caractères **et** confirmation explicite du propriétaire ;
* **domaines racine des plateformes** (tryhackme.com, hackthebox.com, portswigger.net, pentesterlab.com, owasp.org…) : *jamais* ciblables ;
* l'enregistrement ne se fait **jamais à la voix** ni par le LLM (aucun `@outil` Jarvis ne touche ce module — test automatisé).

Non implémenté **volontairement** : authentification/connexion, envoi de formulaires, écriture, exploitation, bruteforce, évasion de contrôles,
exfiltration, persistance, propagation, contournement des règles d'une plateforme.

## 4. Moteur de décision déterministe (`decision.py`)

`suivante(cible, outils, faits, faites, ecartees, conseils, garde, client)` choisit la prochaine étape selon le type de cible, les catégories
autorisées, les outils *réellement* opérationnels et les faits connus (cible joignable ? API détectée ? ports ouverts ?). Chaque étape écartée
est consignée avec sa raison (« nuclei absent… »). Le **LLM ne fait que proposer** (`conseiller.py`) : liste blanche stricte d'étapes, jamais de
commande, de cible, de statut ni de gravité ; le moteur reste maître. Sans LLM (ou LLM lent/indisponible, délai 25 s) l'audit est identique.
Le LLM n'envoie que des compteurs/titres (aucun secret, corps de réponse ou en-tête).

## 5. Statuts et preuves

`POTENTIEL → À VÉRIFIER → REPRODUIT → CONFIRMÉ`, ou `NON CONCLUANT` / `FAUX POSITIF PROBABLE`. Règles déterministes :
* un constat n'est **CONFIRMÉ** que si l'agent de validation l'a *ré-observé* (requête indépendante, signature de contenu, comparaison à la
  référence « page inexistante ») ; une détection d'outil sans ré-observation reste `REPRODUIT` au mieux ;
* un constat qui ressemble à la page catch-all d'une SPA est rétrogradé `FAUX POSITIF PROBABLE` ;
* les dépendances vulnérables (OSV) et secrets de code ne sont jamais « confirmés » comme exploitables : la valeur n'est pas testée.
Champs par constat : id `JSI-…`, titre, description, gravité, composant, ressource, méthode de détection, preuves (requête/statut/extrait masqué),
confiance, impact, recommandation, références CWE/CVE, statut, horodatage.

## 6. Outils externes — détection honnête (`outils.py`)

`detecter()` **exécute** `<outil> --version` : `operationnel` (version lue), `present_en_erreur`, `absent`, ou `non_integrable` (Burp Community : aucune API
d'automatisation ; jamais présenté comme intégré). Lancement : liste argv (pas de shell), environnement assaini, délai, arrêt d'urgence = kill du groupe de processus.
nuclei : modèles *non intrusifs* uniquement (dossiers `http/exposures|misconfiguration|technologies|exposed-panels|miscellaneous|cors`, tags
d'exposition, tags d'attaque exclus), 5 min max ; un arrêt par délai est signalé dans le rapport. ZAP : mode baseline passif seulement.
Les sorties sont parsées par des fonctions pures (testées sur fixtures *étiquetées comme telles*).

## 7. Persistance, reprise, arrêt d'urgence

`logs/security/audits/<id>/{session.json, journal.jsonl, rapport.*}` (session réécrite atomiquement à chaque étape).
Une étape en erreur est consignée ; on relance → seules les étapes non réussies reprennent ; 3 erreurs consécutives arrêtent l'audit. `reprendre(id)`
recharge une session sauvegardée. Arrêt d'urgence : `ArretUrgence` (Event + fichier drapeau) → la garde refuse tout, les sous-processus sont tués.

## 8. HUD

`hud_bridge.securite()` émet `ghost_secu` (état, cible, étape, agents/outils actifs, progression, compteurs, derniers constats triés par statut/gravité,
historique, requêtes) limité à ~4/s ; `hud.py` le rejoue aux clients tardifs ; `hud.html` affiche le panneau et le bouton **EMERGENCY STOP**.

## 9. Compatibilité matérielle

Pure Python + sous-processus ; aucune dépendance lourde. Scan TCP et crawl bornés (budget 800 requêtes, 8 req/s par défaut, corps ≤ 512 Ko).
nuclei est le poste le plus gourmand (~450 Mo RAM mesurés) : il peut être désactivé en ne l'installant pas. PDF via Playwright/Chromium (déjà requis par Jarvis), sinon JSON+HTML.

## 10. Limites connues

Pas de test authentifié (IDOR, JWT, contrôle d'accès, logique métier), pas de XSS DOM, pas de CSRF réel, pas d'exploitation : le rapport les liste dans « limites ».
