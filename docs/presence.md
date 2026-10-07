# Détection de présence

Un service en arrière-plan **ping ton téléphone** sur le wifi pour savoir si tu es là,
et déclenche des ambiances quand tu pars / reviens.

- Absent depuis plus de `seuil_absence` → active le mode `mode_absence` (ex. « off »).
- De retour → active le mode `mode_retour` (ex. lumières douces).
- Désactivable à la voix : « désactive la détection de présence ».
- Phrases d'ambiance : « mode film », « tout éteindre », « je m'en vais »…

## Configuration

```yaml
presence:
  actif: true
  ip: "192.168.1.XXX"   # IP FIXE de ton téléphone sur le réseau (vide = désactivé)
  intervalle: 60         # secondes entre deux pings
  seuil_absence: 600     # secondes d'absence avant le mode "absent" (600 = 10 min)
  mode_absence: "off"    # mode activé quand tu pars
  mode_retour: "retour"  # mode activé à ton retour ("" pour désactiver)
```

### Fixer l'IP du téléphone
Pour que le ping soit fiable, donne à ton téléphone une **IP fixe** (réservation DHCP
dans ta box, ou IP statique dans les réglages wifi). Sinon l'IP change et la détection
devient incohérente.

> Note : sur iPhone, la « private Wi-Fi address » peut faire varier l'adresse MAC —
> désactive-la pour ce réseau, ou utilise une réservation DHCP par appareil.

Les modes (`off`, `retour`, `film`, `stream`…) se définissent dans la section `modes`
de `config.yaml` (voir les exemples commentés dans `config.example.yaml`).
