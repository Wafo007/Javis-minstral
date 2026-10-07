# Reconnaissance musicale (Shazam-like)

« **Jarvis, c'est quoi cette musique ?** » → Jarvis capture ~8 s d'audio, en calcule
l'empreinte et te répond **« C'est [titre] de [artiste] »**. C'est du **Jarvis pur** :
un réflexe local, à la demande — aucune intelligence déléguée, **aucune écoute
musicale en tâche de fond**.

## Deux sources de capture

| Source | Pour quoi | Comment le dire |
|---|---|---|
| **Micro** de la pièce | musique ambiante, radio, une enceinte qui joue | « c'est quoi cette musique / cette chanson », « Shazam ça » |
| **Audio système** (loopback) | le son qui joue **dans le PC** (vidéo, reel, stream) | « c'est quoi la musique **de cette vidéo** » |

La capture micro **suspend proprement le mot d'activation** le temps de l'écoute
(le micro est partagé) et émet un **bip** juste avant, pour ne pas polluer
l'empreinte. La capture système passe par le **loopback WASAPI** du haut-parleur par
défaut (lib `soundcard`).

## Variante fichier (Vault / créatrice)

« **c'est quoi le son de cette vidéo ?** » sur un fichier déjà sur le disque :
`identifier_musique_fichier(chemin)` — pratique pour retrouver le **son tendance**
d'une vidéo d'inspiration. Formats audio courants + pistes audio de vidéos.

## Historique

Chaque reconnaissance est notée dans `notes/musiques.md` (titre, artiste, date,
source). « **Jarvis, c'était quoi la musique de tout à l'heure ?** » →
`derniere_musique`.

**Ajout à Spotify** : « **ajoute-la à ma playlist** » ajoute la dernière musique
reconnue à ta playlist « Jarvis Finds » ; option d'**ajout automatique** à chaque
découverte (`spotify.auto_ajout: true`). Voir [spotify.md](spotify.md).

## Installation (une fois)

`shazamio-core` (le moteur d'empreinte, en Rust) **n'a pas de wheel Python 3.13 sous
Windows** → la reconnaissance tourne dans un **venv isolé Python 3.12**
(`musique/.venv-shazam`), exactement comme les gestes. Installe-le :

```bash
python scripts/setup_musique.py
```

*(Le loopback système utilise `soundcard`, déjà dans les dépendances principales.)*

## Les outils

| Outil | Niveau | MCP | Effet |
|---|---|---|---|
| `identifier_musique` | N1 | **non** | capture micro/système + reconnaissance |
| `identifier_musique_fichier` | N1 | oui | reconnaissance d'un fichier (inoffensif) |
| `derniere_musique` | N1 | non | redonne la dernière reconnue |

## Vie privée

- **À la demande uniquement** — jamais d'écoute continue.
- Ce qui part vers le service Shazam = **l'empreinte des ~8 s capturées**, rien
  d'autre (pas le micro en continu, aucune métadonnée perso).
- Les captures micro/système **ne sont pas exposées au MCP** : le micro reste
  local, hors de portée d'Hermes et du réseau. Seule la variante *fichier* est
  exposée (inoffensive). Les WAV temporaires vont dans `musique/captures/`
  (gitignoré), l'historique dans `notes/` (gitignoré).

## Si ça échoue

- « pas encore installée » → `python scripts/setup_musique.py`.
- « je n'ai pas reconnu » → rapproche la source, monte le volume, réessaie ; les
  morceaux très obscurs ou modifiés peuvent ne pas matcher.
- Audio système muet → vérifie que le son sort bien sur le **haut-parleur par
  défaut** de Windows (c'est lui qui est capté en loopback).
- `shazamio` étant une API Shazam **non officielle**, elle peut casser un jour
  (comme Alexa) — dans ce cas, alternative possible : un service à clé (AudD/ACRCloud).
