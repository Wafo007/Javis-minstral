# Reservation sur le web

Jarvis peut prendre un rendez-vous ou reserver une table a ta place, en pilotant
un vrai navigateur. Le modèle cloud regarde la page (capture + éléments cliquables) et
agit etape par etape jusqu'au formulaire rempli — **puis il s'arrete et te
demande ton accord vocal avant de valider**.

## Utilisation vocale

- « Jarvis, reserve une table pour 2 vendredi 20h au Bistrot sur TheFork »
- « Prends-moi un rendez-vous chez le Dr Martin mardi apres-midi sur Doctolib »
- « Reserve sur https://... » (n'importe quel formulaire de reservation simple)

Deroulement :
1. Une fenetre de navigateur s'ouvre (visible, sur ton 2e ecran).
2. Jarvis navigue, accepte les cookies, cherche, choisit date/heure, remplit
   tes infos (nom / tel / mail depuis `config.yaml`).
3. **Il s'arrete devant le bouton final** et te resume : « Je vais valider la
   reservation : table pour 2 le vendredi 12 a 20h chez Le Bistrot. Tu confirmes ? »
4. Tu dis « oui » -> il clique le bouton final. Tu dis « non » -> il annule.

## Securite (ce qu'il ne fait jamais seul)

- **Aucune validation sans ton « oui »** : le formulaire est rempli, mais le
  bouton « Confirmer » n'est clique qu'apres ton accord vocal.
- **Aucun paiement** : si une page reclame une carte bancaire, il s'arrete et te
  laisse la main (la fenetre reste ouverte).
- **Aucun mot de passe tape** : les champs mot de passe ne sont jamais remplis.
  Pour les sites a login, connecte-toi **une fois** dans la fenetre : le profil
  est persistant, tu restes connecte ensuite (voir plus bas).
- Si le site resiste, il abandonne proprement et te dit ou ca coince.

## Rester connecte (profil persistant)

Le navigateur utilise un profil dedie (`reservation.profil`, defaut
`.profil_reservation/`, non versionne). La 1re fois, connecte-toi toi-meme a
Doctolib / TheFork dans la fenetre : tes cookies sont gardes, les fois suivantes
Jarvis arrive deja connecte. Aucun mot de passe n'est stocke par Jarvis.

## Configuration (`config.yaml`)

```yaml
utilisateur:                 # JAMAIS de mot de passe ici
  nom: "Ton Nom"
  telephone: "06..."
  email: "toi@exemple.fr"

reservation:
  navigateur_visible: true   # false = navigateur invisible (headless)
  profil: ".profil_reservation"
  max_etapes: 22             # nb max d'actions avant d'abandonner
  # modele: "claude-haiku-4-5"   # modele de la boucle vision (defaut = anthropic.modele)
  sites:
    thefork: "https://www.thefork.fr/"
    doctolib: "https://www.doctolib.fr/"
```

Ajoute tes propres raccourcis sous `sites:` (« reserve sur monsite »).

## Sites supportes

- **TheFork**, **Doctolib** : raccourcis fournis.
- **Generique** : n'importe quel formulaire de reservation simple, en donnant
  l'URL. Plus le site est complexe (captcha, etapes multiples inhabituelles),
  plus il peut bloquer — il te le dira.

## Prerequis technique

Playwright + Chromium (deja installes) :

```bash
uv run playwright install chromium
```

Le mode **visible** exige une session bureau (ton PC normal). C'est le cas quand
tu lances Jarvis toi-meme.
