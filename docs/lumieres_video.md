# Lumières vidéo (amaran / Godox)

Piloter ses lumières vidéo à la voix/aux gestes, en **local et temps réel** (aucun
cloud, aucune app propriétaire) — pile dans la doctrine Jarvis pur.

> **Réalité honnête** : ni amaran ni Godox n'ont d'API officielle ; leurs apps sont
> en Bluetooth. Mais on contourne proprement, par des protocoles **locaux**.

## amaran (Aputure) — via un ESP32 (BLE mesh)

L'amaran (200x, 60x…) se pilote en **Bluetooth mesh (Sidus Link)**, impossible
directement depuis un PC. La solution communautaire **[wesbos/amaran-BLE-control](https://github.com/wesbos/amaran-BLE-control)**
utilise un **ESP32 (~5 €)** qui rejoint le mesh et expose une **API HTTP locale** —
**sans l'app Sidus**. Jarvis lui envoie juste des requêtes HTTP.

### Mise en place (côté matériel, une fois)
1. Procure-toi un **ESP32** (n'importe quel modèle courant, ~5 €).
2. Suis le repo **wesbos/amaran-BLE-control** :
   - `npm run setup` — **extrait les clés du mesh** depuis la base de l'app **Amaran
     Desktop** (installe-la et appaire tes lumières une fois), ou saisie manuelle ;
   - applique le patch BLE Mesh à ESP-IDF v5.3.x, `npm run gen-config`, configure le
     Wi-Fi (`wifi_config.h`), puis `idf.py flash monitor`.
3. Note l'**IP de l'ESP32** sur ton réseau → mets `http://<ip>:2708` dans `config.yaml` :
   ```yaml
   amaran:
     url: "http://192.168.1.50:2708"
   ```

### Utilisation (dès que l'ESP32 tourne)
- « **allume la key light à 60 %** »
- « **mets l'amaran en 5600 kelvin** »
- « **passe l'amaran en bleu** »
- « **éteins la lumière vidéo** »

Outil : `controler_amaran` (N1, non exposé au MCP). En interne : `POST /lights/all/on`,
`/off`, `/brightness {value}`, `/cct {brightness,kelvin,gm}`, `/hsi
{brightness,hue,saturation}` (format du firmware wesbos — ajuste si une version change
les routes).

*(Le seul « coût » : monter l'ESP32 une fois. Ensuite tout est instantané et local.)*

## Godox TL60 — via DMX (à venir)

Le TL60 a une **entrée DMX native**. Le plus fiable : une **interface USB-DMX**
(Enttec-like) + contrôle Art-Net/DMX depuis Python. Outil à construire quand tu as
l'interface. *(Alternative : Art-Net → un nœud DMX.)*
