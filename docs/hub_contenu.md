# Hub de contenu — Vault d'inspirations + génération

Connecte tes deux projets à Jarvis :
- **Vault** (`C:\Users\<toi>\Vault`) — tes vidéos Insta/TikTok sauvegardées, indexées.
- **Scripts** (`C:\Users\<toi>\Downloads\Scripts`) — transcription YouTube + écriture de scripts.

## Le pipeline (chaînon manquant : l'indexeur)

```
URL Insta/TikTok
   │  (ingest.py — EXISTANT, non modifié : yt-dlp + faster-whisper + 3 images)
   ▼
Vault\raw\insta_<shortcode>.md   (fiche brute)
   │  (INDEXEUR = core/hub_contenu.py — le "greffier", via Claude)
   │   • résumé + thèmes + tags + format
   │   • APPEND à index.md   (append-only, dédup par <shortcode>)
   │   • enrichit le front-matter de la fiche
   │   • met à jour progression.txt
   ▼
graphe.py  →  thèmes propagés dans raw\ (## Liens) + themes\
build_vault.py  →  vault.html (page offline)
   ▼
(option) miroir Google Drive : index.md + vault.html
```

**Règles (non négociables) :**
- **Jarvis est le SEUL greffier de `index.md`** : append-only, dédup par `<shortcode>`.
  Hermes ne fait que **lire** le Vault (voir docs/hermes.md / 4bis).
- **`ingest.py` n'est pas modifié.** L'enrichissement du front-matter se fait dans
  l'indexeur, sur la fiche que le pipeline vient de créer. Les anciennes fiches sont
  **laissées telles quelles** (parsing tolérant).
- `graphe.py` / `build_vault.py` tournent avec **cwd = racine du Vault** ; Whisper en **CPU**.

## Deux façons d'ajouter une inspiration

1. **Depuis l'iPhone (temps réel)** — partage un reel → raccourci « Inspiration Jarvis »
   → `POST /api/inbox {type:"inspiration", url, commentaire?}` → pipeline en fond →
   **Jarvis annonce à voix haute** « Inspiration ajoutée au vault : *titre* — *auteur* ».
   (Voir docs/iphone.md.)
2. **En lot (existant)** — l'app Raccourcis dépose les liens dans
   `iCloudDrive\...\inbox.txt`, puis `Vault\inbox.bat` lance `ingest.py`. Ensuite,
   rattrape l'indexation : `indexer_manquantes()` (ci-dessous).

## Commandes (module `core/hub_contenu.py`)

```python
from core import hub_contenu as h
# Une URL, pipeline complet (télécharge + indexe + rend) :
h.ingerer_inspiration("https://www.instagram.com/reel/XXXX/", "j'aime le hook")
# Rattraper toutes les fiches de raw\ absentes de l'index :
h.indexer_manquantes()            # ou indexer_manquantes(limite=5)
# Indexer une fiche déjà présente dans raw\ :
h.indexer_fiche(Path(r"C:\Users\<toi>\Vault\raw\insta_XXXX.md"))
```

## Format enrichi des fiches (rétrocompatible)

Les **nouvelles** fiches gardent l'en-tête existant (`source/plateforme/genre/auteur/
duree_s/traite_le/statut`) **et** reçoivent :
```yaml
tags: [mot1, mot2, ...]       # déduits de la transcription
format: talking head|tuto|storytelling|trend|interview|sketch|vlog|demo produit|motivation|autre
themes: [Thème1, Thème2]
date_ajout: AAAA-MM-JJ
duree: m:ss
pourquoi: "ton commentaire iPhone (ex: j'aime le hook)"
```
Les anciennes fiches **sans** ces champs restent valides. C'est ce front-matter qui
rendra `chercher_inspiration` / `generer_idees` vraiment fins (pas du simple grep).

## Configuration (`config.yaml`)

```yaml
integrations:
  vault:   "C:/Users/<toi>/Vault"
  scripts: "C:/Users/<toi>/Downloads/Scripts"
  cookies: "firefox"           # cookies yt-dlp pour l'Instagram privé
hub:
  modele: ""                   # modèle Claude pour l'indexation (vide = anthropic.modele)
  timeout_ingest: 600          # secondes max (téléchargement + Whisper)
  miroir_dossier: ""           # miroir de index.md + vault.html vers un dossier synchro (vide = pas de miroir)
```

### Miroir de consultation à distance (iCloud)
`index.md` + `vault.html` sont copiés vers `hub.miroir_dossier` (remplacement en place),
le **même mécanisme que l'inbox** : un dossier iCloudDrive synchronisé → consultation
depuis le téléphone, **zéro nouvelle installation**.
- Mets un sous-dossier iCloud dédié (ex. `%USERPROFILE%\iCloudDrive\Vault`) dans
  `hub.miroir_dossier` (**pas** la racine iCloud, qui contient tes documents perso).
- Vide = miroir **ignoré** (no-op) ; le reste du pipeline fonctionne. C'est du confort.

## Prérequis (vérifiés)

- Python 3.13 système (pas de venv). `faster-whisper` ✅, `yt-dlp` ✅, `gallery-dl` ✅
  (installé pour les carrousels), `ffmpeg` ✅.
- `build_vault.py` / `graphe.py` : **stdlib pure**, aucune dépendance.
- Whisper : **CPU** (GPU cassé) — `WHISPER_DEVICE=cpu` forcé par le pipeline.

## Dépannage

- **Vidéo privée / indisponible** → le pipeline ne plante pas en silence : il renvoie
  un message clair (« vidéo privée ou indisponible : … ») et Jarvis le dit à voix haute.
  Vérifie que Firefox est connecté à Instagram (cookies).
- **Rien ne s'indexe** → `indexer_manquantes()` compare les `<shortcode>` de `raw\` à
  ceux d'`index.md` ; si un shortcode y est déjà, la fiche est ignorée (dédup).
- **`index.md` semble figé** → normal : append-only. On n'écrase jamais, on ajoute.
- **Accents bizarres dans un terminal** → affichage seulement ; les fichiers sont en UTF-8.

## Génération (Jarvis + Hermes)

**Doctrine** : Jarvis = interface vocale rapide ; **Hermes = moteur** (il lit `/vault` +
`/scripts` en **lecture seule** dans son conteneur Docker, écrit seulement dans `/scripts/drafts`).

**Outils Jarvis** (`tools/contenu.py`) :
- `chercher_inspiration(sujet)` — recherche pondérée dans le vault (côté Jarvis, rapide). `mcp_expose`.
- `generer_idees_contenu()` — **délègue à Hermes** l'analyse du vault + 5 concepts. `mcp_expose`.
- `generer_script(sujet, style?)` — **délègue à Hermes** la rédaction (confirmation requise) ; sortie `drafts/`.
- `lancer_ingestion_youtube(url, cible, whisper?, max?)` — lance `ingest.sh` **côté hôte** (Git Bash)
  en arrière-plan + notif vocale. `mcp_expose` (c'est l'outil qu'Hermes appelle pour le YouTube).

**Skills Hermes** (dans `%LOCALAPPDATA%\hermes\skills\hub-contenu\`) :
- `analyser-vault` — tendances/formats/hooks + concepts (lit `/vault`).
- `generer-script-maison` — écrit dans ta voix (`corrections.md` en autorité max) → `/scripts/drafts`.
- `ingerer-chaine-youtube` — passe par l'outil MCP `lancer_ingestion_youtube` (jobs bash = hôte).
- `creer-une-veille` — met en place une veille hebdo sur un sujet (cron → Telegram).

**Veille IA hebdo** : cron Hermes `veille-ia-hebdo` (vendredi 18h → Telegram). Gérer :
`hermes cron list|run|edit|remove`. En créer d'autres : « crée une veille sur <sujet> » (skill).

### Dépendances de l'ingestion YouTube
`lancer_ingestion_youtube` → `ingest.sh` (projet Scripts) dépend de deux choses :

1. **Firefox installé + une session YouTube/Google connectée.** `ytdlp_run.py` injecte
   `--cookies-from-browser firefox` (**aucun identifiant en clair**) pour passer la
   **bot-detection** de YouTube (`HTTP 429` / « Sign in to confirm you're not a bot »).
   ✅ **Appliqué** (commit Scripts *« fix: cookies navigateur… »*).
   - **Si Firefox n'est pas connecté à YouTube** → yt-dlp échoue sur la bot-detection, et le
     tool l'**annonce à voix haute** (« aucune transcription… »), **jamais d'échec muet**.
2. **Un runtime JS (`deno`) + le solveur de challenge `EJS`** (yt-dlp récent en a besoin pour
   résoudre la signature du player YouTube). ✅ **Réglé** : `deno` installé
   (`winget install DenoLand.Deno`) et `ytdlp_run.py` injecte `--remote-components ejs:github`
   (yt-dlp télécharge le solveur, exécuté par deno). Sans ça : *« Signature solving failed /
   Only images are available »* → échec **annoncé vocalement**, jamais silencieux.
   - ⚠️ `deno` doit être sur le PATH quand le job tourne → **relancer Jarvis** après l'install
     de deno pour qu'il hérite du nouveau PATH.

> L'ingestion **Instagram/TikTok** (le pipeline principal des inspirations) **n'est PAS
> concernée** par ce challenge JS et fonctionne normalement.

## Sécurité

- Les **téléchargements se font côté Jarvis** (cookies Firefox de l'utilisateur) — **aucun
  credential Instagram ne va chez Hermes**.
- `/api/inbox` type `inspiration` est protégé par le token `X-Jarvis-Token` ; il ne
  déclenche qu'un ajout de contenu (pas d'action sensible).
