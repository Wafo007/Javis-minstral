# OBS Studio

Contrôle d'OBS par la voix via le **WebSocket intégré** (OBS 28+, protocole v5).

- `start_stream` / `stop_stream`\* — « lance le direct », « coupe le stream »
- `start_record` / `stop_record` — « enregistre », « arrête l'enregistrement »
- `switch_scene` — « passe sur la scène pause » (liste des scènes récupérée dynamiquement)
- `save_replay` — « clippe ça » (sauvegarde le replay buffer ; le démarre s'il est inactif)

`*` `stop_stream` demande une **confirmation vocale**.

## Configuration

1. Dans OBS : **Outils → Paramètres du serveur WebSocket** → coche **Activer le serveur
   WebSocket**. Note le **port** (4455 par défaut) et le **mot de passe**.
2. Dans `config.yaml` :
   ```yaml
   obs:
     host: "localhost"
     port: 4455
     mot_de_passe: "le-mot-de-passe-du-serveur-websocket"
   ```

Si OBS n'est pas lancé ou le WebSocket désactivé, les outils répondent un message
clair (« OBS ne répond pas… ») sans planter.

## Exposé via MCP
Ces outils sont **exposés via le serveur MCP** (domotique/PC), donc pilotables depuis
Claude Desktop / Hermes. Voir [mcp.md](mcp.md).
