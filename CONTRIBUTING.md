# Contribuer à Jarvis

Merci de vouloir contribuer ! Ce projet a une **architecture volontairement simple**
et des **règles de sécurité non négociables**. Lis ceci avant d'ouvrir une PR.

## Architecture à respecter

### Un outil = un fichier `@outil`
Ajouter une capacité = **une fonction décorée `@outil(...)`** dans `tools/`. Elle est
**auto-découverte** au démarrage (`core/registre.py`) — aucun câblage, aucune liste à
tenir à jour. Copie le patron d'un outil existant (ex. `tools/temps.py`).

```python
from core.registre import outil

@outil(
    nom="mon_outil",
    description="Ce que fait l'outil + QUAND l'utiliser (Claude s'en sert pour décider).",
    parametres={"type": "object", "properties": {
        "param": {"type": "string", "description": "..."}}, "required": ["param"]},
    mcp_expose=False,          # exposé à un client MCP (Hermes/Claude Desktop) ? défaut non
    confirmation=False,        # demande une confirmation vocale ? (voir niveaux)
)
def mon_outil(param: str) -> str:
    return "..."
```

L'outil renvoie une **chaîne** (lue à voix haute), ou un dict `{"image": ...}` pour la vision.

### Niveaux de permission N1 / N2 / N3
Chaque outil a un niveau de sensibilité (`core/registre.py`) :

| Niveau | Sens | `confirmation` | À distance (iPhone) | « toujours autoriser » |
|---|---|---|---|---|
| **N1** | sûr (domotique, lecture, PC) | non | oui | — |
| **N2** | sensible (réversible) | oui | non | mémorisable, révocable |
| **N3** | critique (mail, appels, résa, extinction) | oui | **jamais** | **jamais** |

- Un outil sans `confirmation` est **N1**.
- Un outil `confirmation=True` est **N2**, sauf s'il est listé dans `registre._N3` → **N3**.
- **Une nouvelle action irréversible / coûteuse / externe → N3** (ajoute-la à `_N3`).

### Doctrine Jarvis / Hermes
- **Jarvis détient les clés et le corps** : c'est lui qui exécute les actions et tient
  les credentials.
- **Hermes orchestre et pense** : réflexion, recherche, analyse — jamais d'exécution
  d'action sensible, **aucun credential dans son environnement**.
- N'expose au MCP (`mcp_expose=True`) que des outils **sûrs** — jamais une caméra, un
  micro, ou une action N3.

### Credentials — jamais en dur
- **Tous les secrets vivent dans `config.yaml`** (gitignoré), lus via
  `reglage("section.cle")`. **Jamais** de clé/token/mot de passe en dur dans le code.
- Ajoute les clés dans **`config.example.yaml`** avec des **valeurs factices**
  documentées.

## Toute nouvelle intégration DOIT fournir

1. L'outil (`tools/<nom>.py`) avec `@outil`, niveaux corrects, credentials en config.
2. **`config.example.yaml`** mis à jour (valeurs factices + commentaire).
3. **Une doc `docs/<nom>.md`** pas-à-pas (création de compte/API, OAuth, config,
   dépannage) — niveau débutant, comme `docs/agenda.md`.
4. Si non testé sur matériel réel : une **bannière « ⚠️ Expérimental »** dans la doc.

## Processus : issue → PR → revue

1. **Ouvre une issue** décrivant le besoin/bug (ou commente une issue existante), pour
   éviter le travail en double.
2. **Fork + branche** (`feat/mon-integration`).
3. **PR** vers `main` : description claire, lien vers l'issue, et une **case cochée**
   confirmant : outil `@outil` ✓, niveaux N1-N3 ✓, credentials en config ✓, doc + 
   `config.example` ✓, **aucun secret réel commité** ✓.
4. **Revue** : au moins une relecture. On vérifie l'architecture, la sécurité (niveaux,
   secrets), et la doc.

## Avant de committer (checklist sécurité)

- [ ] `python -m py_compile` passe sur les fichiers modifiés.
- [ ] **Aucun secret réel** : `git diff` ne contient ni clé, ni token, ni mot de passe,
      ni donnée perso. `config.yaml`, `notes/`, tokens = gitignorés.
- [ ] **Documentation généraliste** : aucun matériel présenté comme déjà possédé ou
      installé, aucun nom d'appareil/réseau personnel ; utiliser des placeholders et
      distinguer clairement exemples, prérequis et fonctions futures.
- [ ] `config.example.yaml` à jour (valeurs factices).
- [ ] Doc `docs/<nom>.md` fournie pour toute nouvelle intégration.

## Style

- Français dans les messages utilisateur et les commentaires, comme le reste du code.
- Reste dans l'idiome du fichier voisin (nommage, densité de commentaires).
- Petites PR ciblées > gros fourre-tout.

Merci 🙏 — et amuse-toi bien.
