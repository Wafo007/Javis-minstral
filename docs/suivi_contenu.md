# Suivi de contenus — le pipeline de tes vidéos

Suit l'**avancement** de tes contenus, de l'idée à la publication. C'est du **pur
tracking** : le hub d'inspirations et la génération de scripts vivent ailleurs
(voir [hub_contenu.md](hub_contenu.md)).

**Doctrine** : *Jarvis tient la liste* (écriture à la voix) ; *Hermes la lit
seulement* (outil MCP `etat_contenus`) pour croiser « ce qui m'inspire » (vault)
avec « ce que j'ai en cours » et suggérer les priorités. Jamais d'écriture côté
Hermes, aucun credential chez lui.

## Le fichier : `contenus.yaml`

Une liste **éditable à la main ET par Jarvis** (non versionnée — données perso).
Copie [contenus.example.yaml](../contenus.example.yaml) en `contenus.yaml`.

```yaml
- titre: "5 outils IA gratuits"
  statut: tournage        # idee | script | tournage | montage | publie
  plateforme: youtube     # optionnel
  deadline: 2026-08-20    # AAAA-MM-JJ (optionnel)
  notes: "hook a retravailler"
  cree_le: 2026-08-11
```

Le pipeline est ordonné : **idée → script → tournage → montage → publié**.

## Outils vocaux (côté Jarvis)

| Tu dis… | Outil | Effet |
|---|---|---|
| « nouvelle idée de vidéo : *titre* » | `nouvelle_idee_video` | crée l'entrée en statut `idee` (et l'ajoute aussi à tes **notes** `idees.md`) |
| « passe *titre* en tournage » | `changer_statut_contenu` | fait avancer le statut (titre en recherche floue, statut tolérant à la voix) |
| « où j'en suis ? » | `ou_j_en_suis` | résumé du pipeline (combien d'idées/scripts/…) **+ ce qui est en retard ou à échéance proche + croisement avec ton Google Agenda** |

**Croisement agenda** : `ou_j_en_suis` lit aussi ton **Google Agenda** (21 jours) et
rapproche chaque contenu d'un **créneau** portant le même sujet (« *Callé à
l'agenda : « … » vendredi 14* »), puis liste les prochaines **deadlines** des
calendriers Loopstr. Si l'agenda n'est pas configuré, l'outil **dégrade en
silence** (il rend juste le pipeline) et ne déclenche jamais de connexion OAuth
interactive.

**Le brief du matin** (`faire_brief`) signale automatiquement les contenus **en
retard** ou **à boucler bientôt** (deadline ≤ 3 j du champ `deadline`), à côté des
deadlines de l'agenda. Un contenu `publie` n'est jamais compté en retard.

## Côté Hermes (lecture seule via MCP)

L'outil `etat_contenus` (`mcp_expose=True`) renvoie la liste complète (titre,
statut, plateforme, deadline, notes). Hermes l'appelle pour **croiser tes
inspirations du vault avec tes contenus en cours** et proposer quoi prioriser
(skill `analyser-vault`). Les trois outils d'écriture ci-dessus ne sont **pas**
exposés au MCP : le distant ne peut pas modifier ton pipeline.

> Après ajout de l'outil, **redémarre le serveur MCP** (`python -m jarvis.mcp_server`)
> pour qu'Hermes voie `etat_contenus`.

## Configuration (`config.yaml`)

```yaml
suivi:
  fichier: "contenus.yaml"   # chemin relatif = racine du projet ; absolu accepté
```
