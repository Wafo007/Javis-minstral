# Saisie clavier — écrire à Jarvis, il répond toujours à voix haute

Deux façons de lui parler, **une seule façon de te répondre** :

| Entrée | Comment | Sortie |
|---|---|---|
| Voix | « Hey Jarvis, … » (inchangé) | voix |
| Clavier — HUD | champ **« Écris ta demande… »** en bas du HUD, `Entrée` ou `ENVOYER` | voix |
| Clavier — terminal | taper une ligne dans la fenêtre où tourne `jarvis14.py`, `Entrée` | voix |

Une demande écrite suit **exactement** le même chemin qu'une phrase transcrite : commandes locales, routage,
LLM, outils, permissions N1/N2/N3, puis lecture à voix haute. Elle apparaît aussi dans la transcription du HUD.
Elle n'a pas besoin du mot d'activation et fonctionne même si le micro est coupé.

## Confirmations (permissions inchangées)

- **N1** : exécuté directement, comme à la voix.
- **N2** (sensible, réversible) : Jarvis demande « Tu confirmes ? » à voix haute ; tu peux répondre en **tapant**
  `oui`, `oui toujours` ou `non`. Sans réponse en 20 s, l'action est **annulée**.
- **N3** (mail, appel, suppression, extinction, Astra…) : la confirmation reste **vocale** par défaut. Un « oui »
  tapé est ignoré et jeté. Pour l'autoriser par écrit : `texte.confirmation_ecrite_n3: true` (déconseillé).
- La réponse tapée passe par le même interpréteur strict que la voix (toute négation l'emporte).

## Réglages (`config.yaml`, bloc `texte:`)

```yaml
texte:
  actif: true                     # false = voix uniquement
  console: true                   # accepte aussi le terminal
  longueur_max: 1000              # caractères par message (20 à 4000)
  confirmation_ecrite: true       # N2 confirmable par écrit
  confirmation_ecrite_n3: false   # N3 : false = confirmation vocale obligatoire
  delai_confirmation: 20          # secondes avant annulation (5 à 120)
```

## Protections

- Le champ du HUD utilise le garde-fou existant de `/api/controle` : poste local, en-tête `Host` local (anti DNS
  rebinding), en-tête `X-Jarvis-HUD`, JSON, 8 Ko maximum. Aucune route nouvelle n'est exposée au LAN ni à ngrok.
- Texte nettoyé (caractères de contrôle retirés), borné, file de 5 messages maximum, 0,25 s minimum entre deux envois.
- Le texte est échappé à l'affichage dans le HUD.

## Limites connues

- Mode « serveur sans périphériques » (`poste_principal.serveur_sans_peripheriques`) : la boucle d'écoute n'est pas
  lancée, la saisie clavier n'y est pas active. Elle fonctionne sur le poste qui porte le micro.
- Un message écrit pendant que Jarvis parle attend la fin de sa phrase (il n'interrompt pas la parole).
- Le HUD étant accessible à tout processus local de la machine, la protection est celle du reste du HUD : pour une
  protection plus forte, passer `confirmation_ecrite` à `false` (toutes les confirmations redeviennent vocales).

## Fichiers

`core/entree_texte.py` · `jarvis14.py` (`traiter_texte`, `_traiter_question`, `_confirmer`) · `hud.py` (action
`ecrire`) · `hud.html` (champ de saisie) · `config.example.yaml` · `tests/test_entree_texte.py`.
