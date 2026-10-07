# Bot Discord

Résumé de ton activité Discord par la voix :

- `get_mentions_summary` — « mes mentions Discord » (dernières 24 h)
- `get_channel_summary` — « résume ce qui s'est dit sur Discord aujourd'hui » (tous les
  salons lisibles, pas seulement les mentions)

## Limites importantes (à comprendre)

Un **bot** ne voit que les serveurs où **tu l'as invité** et les salons où il a la
permission de lire. Il **ne peut pas** lire tes messages privés (DM avec d'autres
personnes), ni les serveurs où il n'est pas, ni savoir ce que tu as « lu » (l'état non-lu
est propre à ton compte). On n'utilise **jamais** le token de ton compte perso (interdit
par Discord). D'où « mentions des 24 h » et « messages du jour », pas « non lus ».

## Créer le bot

1. [Portail développeur Discord](https://discord.com/developers/applications) →
   **New Application** → nomme-la.
2. Onglet **Bot** → **Add Bot**. Active **Message Content Intent** (indispensable pour
   lire le contenu des messages).
3. **Reset Token** → copie le token (c'est un secret, ne le partage jamais).
4. Onglet **OAuth2 → URL Generator** : coche `bot`, puis les permissions **View
   Channels** et **Read Message History**. Ouvre l'URL générée pour **inviter le bot**
   sur ton serveur.

## Configuration

```yaml
discord:
  token: "le-token-du-bot"   # secret, jamais versionné
  user_id: "ton-id-discord"  # active le mode développeur puis clic droit sur ton nom → Copier l'ID
```

Sans token, le bot ne se lance pas (le reste de Jarvis fonctionne). Le premier scan peut
être un peu long s'il y a beaucoup de salons ; le résultat est parlé naturellement.

Données perso : ces outils **ne sont pas exposés via MCP**.
