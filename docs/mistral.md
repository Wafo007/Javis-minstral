# Jarvis avec Mistral API — profil Windows 10 / 8 Go RAM

Ce profil évite de télécharger un modèle LLM local avec Ollama. Jarvis conserve
le wake word, faster-whisper, la mémoire, les outils Windows/Web, les confirmations
et le TTS Windows ; seul le raisonnement LLM passe par l'API Mistral.

## 1. Créer la clé Mistral

Créer un compte Mistral, ouvrir Studio > API Keys et créer une clé. Le mode Free
est actuellement disponible par défaut, sans carte bancaire ; il reste soumis aux
limites d'utilisation et de débit de l'offre gratuite.

Documentation officielle : https://docs.mistral.ai/getting-started/quickstarts/developer/first-api-request

## 2. Configuration

Copier `config.example.yaml` vers `config.yaml`, puis mettre :

```yaml
mode: hybride
cloud:
  fournisseur: mistral

mistral:
  cle: "TA_CLE_MISTRAL"
  modele: "mistral-small-latest"
  modele_qualite: "mistral-large-latest"
```

Pour rester dans le profil gratuit, utiliser principalement `mistral-small-latest`.
Le profil `qualite` est conservé pour les comptes ayant accès au modèle configuré.

## 3. Installation Windows

Depuis PowerShell dans le dossier du projet :

```powershell
uv sync
uv run python scripts/doctor.py
```

Puis :

```powershell
uv run python jarvis14.py
```

Dire ensuite : `Hey Jarvis`.

## 4. Transcription vocale

Pour Windows 10 avec 8 Go RAM, `config.example.yaml` utilise désormais :

```yaml
whisper:
  modele: "small"
```

Le modèle Whisper reste local. Il n'est donc pas envoyé à Mistral. Le premier
lancement télécharge le modèle Whisper demandé.

## 5. Function calling

Les outils Jarvis ne sont pas exécutés par Mistral lui-même. Mistral choisit un
outil et génère ses arguments ; Jarvis exécute ensuite l'outil localement et
renvoie le résultat au modèle. Cela conserve les protections et confirmations
déjà présentes dans Jarvis.

## 6. Retour au LLM local

Pour repasser à Ollama :

```yaml
mode: local
```

et configurer la section `ollama` comme auparavant.

## 7. Diagnostic

Si Jarvis ne répond pas :

```powershell
uv run python scripts/doctor.py
```

Vérifier en priorité :

- `cloud.fournisseur: mistral`
- `mistral.cle` présente
- Internet disponible
- microphone Windows détecté
- Whisper `small` téléchargé au premier lancement

## 8. Dépendances et stockage

Aucun SDK Mistral supplémentaire n'est nécessaire : le projet utilise déjà le
client OpenAI installé et pointe celui-ci vers `https://api.mistral.ai/v1`, une
compatibilité officiellement documentée par Mistral pour Chat Completions.

Le profil recommandé ne télécharge donc pas Qwen/Ollama. Il reste toutefois les
dépendances générales du projet et le modèle Whisper local. Playwright peut aussi
télécharger Chromium si les fonctions navigateur sont utilisées.
