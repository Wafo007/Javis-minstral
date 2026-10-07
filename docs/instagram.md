# Analyse Instagram

`instagram_resume` te dit ce qui a bouge sur ton compte **par rapport a la veille** :
abonnes gagnes/perdus, vues prises par tes dernieres videos, nouvelles publications.
Jarvis garde un instantane quotidien en local (`logs/instagram/`) et compare.

> « Jarvis, quoi de neuf sur Instagram ? » / « mes stats Insta »

Via l'**API Graph officielle de Meta** (aucun scraping). Il faut un compte
**Business ou Createur** et un token. Donnees perso : jamais expose via MCP.

## Prerequis

1. **Compte Instagram Business ou Createur** (Parametres Insta -> Compte -> passer en
   compte pro), **lie a une page Facebook**.
2. Un compte developpeur sur [developers.facebook.com](https://developers.facebook.com).

## Creer l'acces (pas a pas)

1. **Cree une app** : developers.facebook.com -> Mes apps -> Creer une app -> type
   « Entreprise ». Ajoute le produit **Instagram Graph API** (ou « Instagram »).
2. Ouvre l'**explorateur d'API Graph** (Outils -> Graph API Explorer). Selectionne
   ton app, puis « Generer un token d'acces » en cochant les permissions :
   `instagram_basic`, `instagram_manage_insights`, `pages_show_list`,
   `pages_read_engagement`. Autorise avec ton compte.
3. **Trouve l'ID de ton compte Insta** : dans l'explorateur, lance
   `me/accounts` -> note l'`id` de ta page. Puis
   `{id_page}?fields=instagram_business_account` -> l'`id` renvoye est ton
   **user_id Instagram**.
4. **Token longue duree** : le token de l'explorateur dure ~1h. Echange-le contre un
   token **60 jours** :
   ```
   GET https://graph.facebook.com/v21.0/oauth/access_token
       ?grant_type=fb_exchange_token
       &client_id={app_id}&client_secret={app_secret}
       &fb_exchange_token={token_court}
   ```
   (app_id/app_secret sont dans Parametres -> General de ton app.)
5. Mets le tout dans `config.yaml`. Un **ou plusieurs comptes** :
   ```yaml
   instagram:
     version_api: "v21.0"
     dossier: "logs/instagram"
     comptes:
       - nom: "principal"        # le nom que tu diras a la voix
         user_id: "ton_id_instagram"
         access_token: "ton_token"
       - nom: "pro"              # 2e compte (optionnel)
         user_id: "..."
         access_token: "..."
   ```
   (L'ancien format `access_token:` / `user_id:` a la racine reste accepte pour un
   seul compte.)

## Utilisation

- Le **1er appel** enregistre un instantane (« je pourrai te donner les variations
  des demain »).
- Les appels suivants comparent a la veille : « +37 abonnes depuis hier (total 1037).
  Cote videos : "Ma video" +250 vues... ».

Un instantane par jour est garde ~30 jours dans `logs/instagram/` (local, non
versionne). Pour un suivi fiable, demande le resume une fois par jour.

## Renouvellement automatique du token

Les tokens Instagram durent ~60 jours. **Jarvis les prolonge tout seul** : au
demarrage et a chaque resume, il renouvelle les tokens ages de plus de 10 jours
(endpoint `refresh_access_token`) et memorise le nouveau dans
`logs/instagram/tokens.json` (jamais dans `config.yaml`). Tu n'as donc rien a
refaire tant que tu lances Jarvis au moins une fois par ~50 jours. Pour forcer :
dis « rafraichis mes tokens Instagram ». Si un token a vraiment expire (Jarvis pas
lance depuis 60+ jours), il faudra en regenerer un (etape 4) et le recoller.

## Limites honnetes
- Les **vues** utilisent la metrique `views` (repli `plays`) de l'API ; certaines
  metriques dependent du type de media et de l'API Meta du moment.
- Ca ne marche que sur un compte **Business/Createur** (pas un compte perso).
