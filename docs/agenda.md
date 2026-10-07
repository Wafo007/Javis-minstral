# Google Agenda + deadlines Loopstr

Jarvis lit **tous** tes agendas Google (y compris les agendas abonnes iCal),
cree et supprime des evenements (avec confirmation vocale), et suit tes echeances
de partenariats depuis ton flux **Loopstr**.

- `get_events(periode)` : « j'ai quoi demain ? », « mon planning de la semaine ? »
- `create_event(...)` : « ajoute rdv coiffeur jeudi 15h » (confirmation avant creation)
- `delete_event(...)` : « annule mon rdv coiffeur » (confirmation)
- `get_deadlines(periode)` : « mes deadlines de partenariats »
- Les deadlines de la semaine sont aussi ajoutees au **brief du matin**.

Toutes ces donnees sont **privees** : aucun de ces outils n'est expose via MCP.

---

## 1. Creer les identifiants Google (pas a pas)

Une seule fois, sur [console.cloud.google.com](https://console.cloud.google.com) :

1. **Cree un projet** (menu en haut a gauche -> « Nouveau projet », nom au choix,
   ex. « Jarvis »), puis selectionne-le.
2. **Active l'API Agenda** : menu -> « APIs et services » -> « Bibliotheque » ->
   cherche **Google Calendar API** -> **Activer**.
3. **Ecran de consentement OAuth** : « APIs et services » -> « Ecran de consentement
   OAuth » -> type **Externe** -> renseigne un nom d'application et ton email ->
   Enregistre. Dans **Utilisateurs test**, **ajoute ton adresse Gmail**
   (ton-adresse@gmail.com). (Reste en mode « Test » : suffisant pour un usage perso.)
4. **Cree les identifiants** : « APIs et services » -> « Identifiants » -> « Creer
   des identifiants » -> **ID client OAuth** -> Type d'application : **Application de
   bureau** -> nom au choix -> **Creer**.
5. **Telecharge le JSON** (bouton de telechargement a cote du client cree), renomme-le
   **`google_credentials.json`** et place-le a la racine du projet
   (`C:\Users\ton-utilisateur\jarvis-vocal\`).

> Ce fichier et le `google_token.json` (cree ensuite) sont **gitignores** : ils ne
> partent jamais sur GitHub.

## 2. Premiere autorisation + liste de tes agendas

Lance :

```bash
uv run python -m tools.agenda
```

Une page web s'ouvre : choisis ton compte Google, autorise l'acces a l'agenda.
Un `google_token.json` est cree (tu n'auras plus a le refaire). Le script affiche
ensuite **la liste de tous tes agendas** avec leur nom.

## 3. Choisir les agendas a lire

Copie dans `config.yaml`, sous `agenda.calendriers`, les **noms** (ou ids) des
agendas que Jarvis doit inclure — pense a mettre ton agenda principal **et** ton
agenda abonne (deadlines Loopstr si tu l'as ajoute a Google) :

```yaml
agenda:
  calendrier_principal: "primary"   # ou creer/supprimer (ton agenda principal)
  calendriers:                      # LECTURE : laisse vide pour TOUT inclure
    - "Mon agenda"
    - "Loopstr - Deadlines"
```

Laisse la liste **vide** pour inclure tous tes agendas.

## 4. Deadlines Loopstr (flux iCal direct)

Independamment de Google, l'outil `get_deadlines` lit directement ton flux iCal
Loopstr. Recupere l'URL d'abonnement iCal dans Loopstr et mets-la dans
`config.yaml` :

```yaml
loopstr:
  url: "https://.../loopstr.ics"
```

Jarvis rafraichit le flux a chaque appel (cache de 15 min), distingue tes
**deadlines** (brief, tournage, V1, publication...) de tes **periodes de conge**,
et integre les deadlines de la semaine a ton brief du matin.

## Regles de securite

- **Creation** uniquement dans l'agenda principal. Les agendas abonnes (iCal) sont
  **en lecture seule** : si tu demandes de supprimer un evenement qui en vient,
  Jarvis refuse proprement et te renvoie a la source.
- **create_event** et **delete_event** demandent une **confirmation vocale** : Jarvis
  repete l'evenement avant d'agir.

## Depannage

- « identifiants Google absents » : `google_credentials.json` n'est pas a la racine
  (etape 1.5).
- Ecran « application non verifiee » : clique « Parametres avances » -> « Continuer »
  (normal en mode Test), ou verifie que ton email est bien dans les utilisateurs test.
- Un agenda manque dans les reponses : il n'est pas dans `agenda.calendriers`
  (ou relance `uv run python -m tools.agenda` pour revoir la liste).
