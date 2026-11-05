# Piloter un telephone Android depuis Jarvis (ADB, sans app)

Testé avec un **faux téléphone** uniquement (`tests/test_mobile.py`). Le comportement réel sur un Tecno POP 3 (BF7, Android 12) est à
valider avec le guide ci-dessous.

## Ce que Jarvis sait faire

| Tu dis | Outil | Niveau |
|---|---|---|
| « lance WhatsApp sur mon téléphone » | `mobile_lancer_application` (vérifie que l'app est au premier plan) | N1 |
| « quelle est la batterie de mon téléphone ? » | `mobile_statut` (batterie, charge, écran, Wi-Fi/réseau, app active) | N1 |
| « mets pause / musique suivante / monte le volume sur mon téléphone » | `mobile_lire_media` | N1 |
| « retour / accueil sur mon téléphone », défilement | `mobile_touche`, `mobile_defiler` | N1 |
| notification envoyée au téléphone, lien web ouvert | `mobile_envoyer_notification`, `mobile_ouvrir_url` | N1 |
| toucher un bouton par son texte, taper du texte | `mobile_toucher`, `mobile_taper_texte` | **N2** (confirmation) |
| lire l'écran, capturer l'écran, lire les notifications, position, **photo** | `mobile_lire_ecran`, `mobile_capture_ecran`, `mobile_lire_notifications`, `mobile_position`, `mobile_photo` | **N2** (confirmation) |

N2 = Jarvis demande « tu confirmes ? » ; tu peux répondre « toujours autoriser » (révocable) pour qu'il agisse seul.
Aucun de ces outils n'est exposé au MCP, au pont iPhone ni à Hermes. Les phrases sans « sur mon téléphone/portable » restent des
commandes PC (`lance WhatsApp` ouvre toujours WhatsApp sur Windows).

## Installation (une fois, ~10 min)

1. **ADB sur le PC** : `winget install Google.PlatformTools` (ou télécharge « SDK Platform-Tools » sur developer.android.com, dézippe, et
   mets `mobile.adb_chemin: 'C:\...\platform-tools\adb.exe'` dans `config.yaml`). Gratuit, aucun Visual C++.
2. **Téléphone** : Paramètres → À propos du téléphone → appuie 7 fois sur « Numéro de build » → Options pour les développeurs →
   active **Débogage USB** puis **Débogage sans fil** (Android 11+, donc OK sur ton Android 12). Même Wi-Fi que le PC.
3. Dans « Débogage sans fil » → **Associer un appareil avec un code** : tu vois `IP:PORT` et un code à 6 chiffres.
   `uv run python scripts/mobile_appairer.py pair IP:PORT_APPAIRAGE CODE`
4. Sur l'écran principal « Débogage sans fil », note l'`IP:PORT` de **connexion** (autre port) :
   `uv run python scripts/mobile_appairer.py connect IP:PORT_CONNEXION` puis mets-le dans `config.yaml` → `mobile.appareil`.
5. `uv run python scripts/mobile_appairer.py diag` doit afficher « OK : <modèle> Android 12 ... ». Accepte la fenêtre
   « Toujours autoriser cet ordinateur » sur le téléphone.
6. Copie le bloc `mobile:` de `config.example.yaml` dans ton `config.yaml`. Alias d'apps : `mobile.apps`.

**Si « Débogage sans fil » est absent sur ton Tecno** : branche le câble USB, accepte l'autorisation, puis `adb tcpip 5555`,
débranche, et `connect IP_DU_TELEPHONE:5555`.

## Limites réelles (à connaître)

- Le port de connexion sans fil **change** après un redémarrage du téléphone ou un changement de Wi-Fi : relance `connect` (Jarvis
  tente seul de se reconnecter à `mobile.appareil`, mais si le port a changé il te le dira).
- **Téléphone verrouillé par code/empreinte** : Jarvis peut réveiller l'écran mais **ne connaît pas et ne saisit pas ton code** ;
  déverrouille toi-même avant les actions d'écran/caméra.
- Les apps « sécurisées » (banque, certains messageries) **bloquent les captures et la lecture d'écran** : Jarvis le dit, il ne
  contourne pas.
- `input text` ne gère que l'**ASCII** (pas d'accents) : Jarvis refuse plutôt que de tronquer.
- Photo : Jarvis ouvre l'app Caméra, déclenche l'obturateur puis récupère le nouveau fichier ; il ne dit « photo prise » que s'il
  constate un nouveau fichier. Selon l'app caméra de Tecno cela peut demander un réglage (autoriser la caméra).
- Position : dernière position connue du système (peut être absente si la localisation est coupée).
- Le micro du **téléphone** n'est pas utilisé : tu parles au micro du PC (ou à un satellite).
- Sécurité : le débogage sans fil donne au PC appairé un contrôle étendu du téléphone — appaire seulement ton PC, sur un Wi-Fi de
  confiance, et coupe « Débogage sans fil » quand tu n'en as pas besoin.

## Et ton application W4FO ?

Pas nécessaire pour cette première version (aucune app à installer). Elle servirait pour ce qu'ADB ne fait pas bien : recevoir les
notifications **en direct** (service d'accessibilité), streamer le micro/la caméra du téléphone vers Jarvis, ou rester connectée sans
réappairage. Cela se construirait avec Android Studio sur ton PC (je ne peux pas compiler d'APK ici) ; envoie le ZIP **sans clés ni
keystore** si tu veux que j'évalue ce qui est réutilisable.
