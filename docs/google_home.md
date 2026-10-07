# Google Home / Nest (⚠️ Expérimental)

> **⚠️ Expérimental — non testé sur matériel réel, retours bienvenus via les
> [issues](https://github.com/sosoj92/jarvis-assistant-vocal/issues).** Si tu as des
> appareils Nest et que tu testes, dis-nous ce qui marche (ou pas) !

## Le choix d'API et ses limites (honnête)

La seule API Google **officielle et stable** est la **Smart Device Management (SDM)**.
Elle permet de **lister tes appareils Nest et lire leur état**, et de piloter les
**Nest** (thermostats, caméras). **Ce qu'elle ne fait PAS** :

- ❌ **Pas** de contrôle on/off générique de lumières/prises tierces liées à Google Home.
- ❌ **Pas** de trait « luminosité ».
- ❌ Il n'existe **aucune API serveur/Python officielle** pour piloter des lumières
  Google Home (les nouvelles « Google Home APIs » 2024 sont des **SDK mobiles** seulement).

**Donc :** cette intégration liste tes appareils Nest et leur état (fiable), mais pour
**allumer/éteindre ou régler une lumière**, elle renvoie un message clair : ce n'est
pas supporté officiellement. Pour des **lumières**, deux voies fiables :
1. **L'intégration native** — les **Philips Hue** sont déjà gérées par Jarvis
   ([docs/hue.md](hue.md)).
2. **Un pont [Home Assistant](https://www.home-assistant.io/)** qui réexpose tes
   appareils via une API locale (piste pour une future intégration).

## Ce que fournit l'outil

| Outil | Niveau | Effet |
|---|---|---|
| `google_home_etat` | N1 | Liste les appareils Nest + état (connectivité, température…) |
| `google_home_allumer` | N2 | Tente l'allumage — message honnête si non supporté |
| `google_home_luminosite` | N2 | Non supporté par SDM — message clair |

---

## Tutoriel pas-à-pas (débutant)

### 1. Projet Google Cloud + API SDM
1. Va sur [console.cloud.google.com](https://console.cloud.google.com/) → crée un
   **projet** (ou réutilise celui de Google Agenda).
2. **APIs & Services → Library** → cherche **« Smart Device Management API »** →
   **Enable**.

### 2. Écran de consentement OAuth
1. **APIs & Services → OAuth consent screen** → type **External** → renseigne le nom
   de l'app et ton e-mail.
2. Ajoute **ton compte Google** dans **Test users** (sinon l'accès est refusé).

### 3. Identifiants OAuth (client)
1. **APIs & Services → Credentials → Create Credentials → OAuth client ID** → type
   **Web application**.
2. Dans **Authorized redirect URIs**, ajoute `https://www.google.com` (on l'utilisera
   pour récupérer le code manuellement).
3. Note le **Client ID** et le **Client secret**.

### 4. Device Access (inscription développeur — 5 $ une fois)
1. Va sur la [Device Access Console](https://console.nest.google.com/device-access) →
   accepte les conditions → **paye les 5 $** (frais unique).
2. **Create project** → note le **Project ID** (c'est le `project_id`).
3. Dans le projet, renseigne ton **OAuth Client ID** (étape 3).

### 5. Lier ton compte Google et obtenir le `refresh_token`
1. Ouvre dans le navigateur (remplace `PROJECT_ID` et `CLIENT_ID`) :
   ```
   https://nestservices.google.com/partnerconnections/PROJECT_ID/auth?redirect_uri=https://www.google.com&access_type=offline&prompt=consent&client_id=CLIENT_ID&response_type=code&scope=https://www.googleapis.com/auth/sdm.service
   ```
2. Autorise l'accès à tes appareils Nest. Tu es redirigé vers `https://www.google.com/?code=CODE...` →
   **copie le `code`** dans l'URL.
3. Échange le code contre un **refresh_token** (dans un terminal, remplace les valeurs) :
   ```bash
   curl -s -X POST https://oauth2.googleapis.com/token \
     -d client_id=CLIENT_ID -d client_secret=CLIENT_SECRET \
     -d code=CODE -d grant_type=authorization_code \
     -d redirect_uri=https://www.google.com
   ```
   La réponse contient `"refresh_token": "1//...."` → **c'est ta clé** (elle ne
   s'affiche qu'à la **première** autorisation ; si tu la rates, refais l'étape 5.1
   avec `prompt=consent`).

### 6. `config.yaml`
```yaml
google_home:
  project_id:    "ton-project-id-device-access"
  client_id:     "xxxxx.apps.googleusercontent.com"
  client_secret: "GOCSPX-xxxxx"
  refresh_token: "1//xxxxx"
```
Redémarre Jarvis, puis : **« Jarvis, mes appareils Google Home »**.

---

## Dépannage

- **« refresh_token » absent de la réponse** → tu ne l'obtiens qu'à la 1re autorisation.
  Refais l'étape 5.1 avec `prompt=consent` (force un nouveau consentement).
- **403 / access_denied** → ajoute ton compte dans **Test users** de l'écran de
  consentement, et vérifie que l'API SDM est **Enable**.
- **Aucun appareil listé** → l'API SDM ne voit que les **Nest**. Les lumières/prises
  tierces n'apparaissent pas (limite officielle, voir en haut).
- **invalid_client** → Client ID/secret erronés ou projet Device Access mal lié.

## Sécurité

Les identifiants vivent **uniquement dans `config.yaml`** (gitignoré) — jamais en dur.
`refresh_token` = à traiter comme un mot de passe. Ces outils sont **N1/N2** (jamais N3).
