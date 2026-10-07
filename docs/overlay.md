# Overlay de réponses (fenêtre flottante)

Une mini-fenêtre discrète qui affiche **à l'écrit ce que Jarvis dit**, en complément
(ou à la place) de la voix. C'est du **Jarvis pur** : affichage **local**, temps réel,
zéro réseau. **Windows uniquement** (ailleurs, c'est simplement ignoré).

## La règle d'or : jamais de vol de focus

L'overlay **n'interrompt jamais** ce que tu fais (jeu, montage, call) :

- **Pas de focus volé** (`WS_EX_NOACTIVATE`) — il ne fait jamais tabber ton jeu.
- **Clic-transparent** (`WS_EX_TRANSPARENT`) par défaut : les clics passent au
  travers. Il ne devient cliquable **que quand la souris le survole**, pour pouvoir
  l'**épingler / copier** (un clic dessus copie le texte et empêche la disparition
  auto).
- **Toujours au-dessus** (topmost) mais **opacité** réglable.
- **Invisible en stream** (`SetWindowDisplayAffinity` / `WDA_EXCLUDEFROMCAPTURE`) :
  tu le vois, **OBS/game-capture ne le voient pas** — tes réponses perso
  n'apparaissent pas en live. Activé par défaut (`overlay.exclure_obs: true`).

> **Limite honnête** : un jeu en plein écran **exclusif** (pas *borderless*) peut
> masquer tout overlay, quel qu'il soit. La plupart des jeux tournent en borderless
> (donc OK) ; en cas de souci, passe le jeu en « fenêtré sans bordure ».

## Quand la fenêtre s'affiche (routage automatique, pas de commande)

Pas besoin de dire « affiche » : Jarvis décide **seul** si une réponse mérite la
fenêtre, à deux niveaux.

1. **Hint par outil** (décorateur `@outil(..., affichage=...)`) :
   - `toujours` → musique, budget/stats, listes, minuteurs, **retours d'Hermes** ;
   - `jamais` → acquittement d'action simple ;
   - `auto` (défaut) → heuristique ci-dessous.
2. **Heuristique de contenu** (mode `auto`, dans le core) : la fenêtre s'affiche si la
   réponse est **consultable** — plus de ~200 caractères, une **liste** (multi-lignes),
   **plusieurs nombres** (horaires, prix, stats), ou une **entité citée** (« titre »,
   nom, lieu). Sinon (ex. « C'est fait. », « Il est 22h10. ») → **voix seule**.

**Règle** : consultable → **fenêtre + voix** ; acquittement éphémère → **voix seule**.

**Surcharge ponctuelle** : après une réponse, dis « **affiche-le** » (ou « montre-le
à l'écran ») → `afficher_reponse` réaffiche la dernière réponse en fenêtre.

## Coût nul au repos

Fenêtre native **tkinter** (aucun paquet à installer) pilotée en direct depuis
Jarvis (pas de serveur en plus). Tant qu'aucune réponse n'est affichée, la fenêtre
est **retirée** (`withdraw`) : elle ne coûte rien.

## Cartes (contenu intelligent, extensible)

Le texte de la réponse, plus selon le contexte une carte typée :

- **musique** 🎵 : titre/artiste en gros (après « c'est quoi cette musique »),
- **météo** : icône + température,
- **minuteur** : temps restant,
- **réponse** : texte générique (par défaut).

Le système est extensible : une entrée par type dans `_CARTES` (`overlay.py`).

## Réglages

Dans `config.yaml` (section `overlay:`) **et à la voix** :

| Réglage | Voix | Config |
|---|---|---|
| Afficher / masquer | « **affiche / masque les réponses** » | `overlay.actif` |
| Mode silencieux visuel (répondre **sans parler**) | « **réponds sans parler** » / « **reparle** » | `overlay.muet_visuel` |
| Opacité | « rends l'overlay plus transparent » | `overlay.opacite` |
| Écran cible | « mets l'overlay sur le 2e écran » | `overlay.ecran` |
| Invisible en stream | « cache l'overlay du stream » | `overlay.exclure_obs` |
| Coin, taille, durée, marge | — | `overlay.coin/largeur/duree_min/duree_max/marge` |

**Mode silencieux visuel** : idéal en call/stream — tu poses une question à voix
basse, la réponse **s'affiche sans que Jarvis parle**.

## Outils

| Outil | Niveau | MCP | Effet |
|---|---|---|---|
| `afficher_reponses` | N1 | non | affiche / masque l'overlay |
| `mode_silencieux_visuel` | N1 | non | répondre sans voix (overlay seul) |
| `reglage_overlay` | N1 | non | opacité / écran / exclusion OBS |

Non exposés au MCP : l'overlay est sur **ton** écran, jamais piloté à distance ni
par Hermes.

## Voir le rendu sans lancer Jarvis

```bash
python overlay.py
```
Joue une petite démo (carte musique, météo, réponse) pour vérifier position,
opacité et écran cible.
