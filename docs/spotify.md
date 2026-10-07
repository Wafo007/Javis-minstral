# Spotify — playlist des musiques reconnues

Quand Jarvis identifie une musique (« c'est quoi cette musique ? »), il peut
l'**ajouter à une playlist Spotify** — à la voix (« ajoute-la à ma playlist ») ou
**automatiquement**. La playlist par défaut : **« Jarvis Finds »** (créée si absente).
Jarvis peut aussi lancer directement un titre ou une playlist, sans passer par
Astra : « joue *Blinding Lights* sur Spotify », « lance ma playlist Chill ».

## Mise en route (une fois)

### 1. Crée une app Spotify
1. Va sur **https://developer.spotify.com/dashboard** → *Create app*.
2. Note le **Client ID** et le **Client secret**.
3. Dans les *Settings* de l'app, ajoute l'**URI de redirection EXACTE** :
   `http://127.0.0.1:8899/callback`

### 2. `config.yaml`
```yaml
spotify:
  client_id: "ton-client-id"
  client_secret: "ton-client-secret"
  playlist: "Jarvis Finds"     # nom de la playlist cible
  auto_ajout: false            # true = ajout AUTO à chaque musique reconnue
  appareils: {}                # ex. {cuisine: "Jarvis Cuisine"}
```

### 3. Connexion
```bash
python scripts/spotify_login.py
```
Ton navigateur s'ouvre → autorise. Le **refresh_token** est sauvé dans
`logs/spotify/token.json` (gitignoré) et réutilisé ensuite. Redémarre Jarvis.

## Utilisation

- **À la voix** : après « c'est quoi cette musique ? », dis « **ajoute-la à ma
  playlist** » → l'ajoute à *Jarvis Finds* (évite les doublons).
- **Automatique** : `spotify.auto_ajout: true` → **chaque musique reconnue en direct**
  (micro ou audio système) est ajoutée en tâche de fond, sans rien dire. *(L'ajout
  auto ne s'applique PAS à l'identification d'un fichier — seulement aux découvertes
  live.)*
- Titre précis : « ajoute *Blinding Lights* de The Weeknd à ma playlist ».
- Lecture : « joue *Blinding Lights* sur Spotify », « lance ma playlist Chill ».
- Contrôles locaux : « pause », « musique suivante », « musique précédente ».

## Lecture dans les pièces satellites

Un satellite audio peut aussi devenir un récepteur **Spotify Connect**. Installe
un client compatible (par exemple [Raspotify](https://github.com/dtcooper/raspotify)
ou [librespot](https://github.com/librespot-org/librespot)) sur l'appareil de la
pièce, donne-lui un nom distinct, puis associe la pièce à ce nom :

```yaml
spotify:
  appareils:
    cuisine: "Jarvis Cuisine"
    salon: "Jarvis Salon"
```

La `piece` déclarée dans `satellites[]` est transmise automatiquement aux outils
Spotify. Ainsi, « lance Spotify » ou « lance ma playlist Chill » depuis la cuisine
cible son récepteur ; pause, précédent et suivant restent dans la même pièce. Une
commande prononcée sur le PC conserve la sortie locale.

Après l'installation d'un nouveau récepteur, sélectionne-le une première fois dans
**Appareils disponibles** de l'application Spotify officielle. Spotify Premium est
requis par librespot/Raspotify.

Sur un satellite Linux où Jarvis et Spotify partagent la même enceinte, privilégie
le backend ALSA avec le périphérique `dmix` de la carte. Il conserve l'isolation
systemd de Raspotify tout en permettant le mixage des deux sources :

```bash
sudo install -d -m 755 /etc/systemd/system/raspotify.service.d
sudo systemctl edit raspotify
# Ajouter dans le drop-in :
# [Service]
# Environment="LIBRESPOT_BACKEND=alsa"
# Environment="LIBRESPOT_DEVICE=<PCM_ALSA_PARTAGE>"
# Environment="ALSA_CONFIG_PATH=/etc/asound.conf"
sudo systemctl daemon-reload
sudo systemctl restart raspotify
```

`aplay -l` donne le nom de la carte. Pour une enceinte USB limitée à 48 kHz,
déclare dans `asound.conf` un PCM `plug` au-dessus d'un PCM `dmix` fixé au taux
du périphérique, puis place le nom de ce PCM dans `LIBRESPOT_DEVICE`. `plug`
convertit les 44,1 kHz de Spotify et `dmix` permet aux clients ALSA qui utilisent
ce même PCM de partager la sortie. Une sortie dédiée peut utiliser directement
`plughw:CARD=<NOM_CARTE_ALSA>,DEV=0`, mais elle sera généralement exclusive.
Évite de désactiver
`PrivateUsers` uniquement pour joindre PulseAudio : le backend ALSA est plus
adapté au service système durci fourni par Raspotify.

## Les outils

| Outil | Niveau | MCP | Effet |
|---|---|---|---|
| `ajouter_a_playlist` | N1 | non | ajoute la dernière musique reconnue (ou un titre donné) |
| `lancer_spotify` | N1 | non | ouvre Spotify localement ou reprend dans la pièce du satellite |
| `lire_spotify` | N1 | non | recherche et lance un titre ou une playlist |
| `controler_spotify` | N1 | non | pause/reprend ou change de piste dans une pièce satellite |

## Sécurité / vie privée

- `client_secret` et le **refresh_token** sont des secrets : `config.yaml` et
  `logs/` sont **gitignorés**. Les droits demandés sont limités aux playlists
  (`playlist-read/modify`) et au contrôle Spotify Connect
  (`user-read/modify-playback-state`).
- Non exposé au MCP : Hermes/le réseau ne peuvent pas toucher à ta playlist.
- La lecture automatique utilise les permissions Spotify Connect
  `user-read-playback-state` et `user-modify-playback-state`. Elle nécessite un
  compte Premium et un appareil Spotify disponible. Sans cela, Jarvis ouvre le
  bon résultat dans l'application, toujours sans Astra.
- API **officielle** Spotify (contrairement à Alexa) : stable, ne « casse » pas.
