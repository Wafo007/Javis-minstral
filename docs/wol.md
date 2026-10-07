# Extinction propre et réveil d'un PC

Jarvis sait effectuer une **extinction locale contrôlée**. Le réveil dépend ensuite
du matériel disponible : Wake-on-LAN, gestion d'alimentation hors bande, ou prise
connectée compatible avec le démarrage au retour du courant.

## État des fonctions

| Fonction | État |
|---|---|
| Extinction vocale avec confirmation N3 et délai annulable | disponible |
| Scène locale avant extinction | disponible |
| Wake-on-LAN | configuration système documentée ; émission à effectuer depuis un autre appareil |
| Cycle automatique d'une prise connectée | non implémenté dans Jarvis |

Une documentation ou un exemple de matériel ne signifie pas qu'il est présent
chez l'utilisateur. Les options ci-dessous sont interchangeables selon le PC, le
réseau et les équipements disponibles.

## 1. Extinction sûre avec Jarvis

L'outil `eteindre_pc` est classé **N3** :

- confirmation vocale locale obligatoire à chaque utilisation ;
- délai annulable avant l'arrêt ;
- aucune exposition MCP et aucun déclenchement distant ;
- scène lumineuse facultative avant l'arrêt.

```yaml
assistant:
  scene_extinction: "off"    # "" pour ne jouer aucune scène
  delai_extinction: 30       # secondes, pendant lesquelles l'arrêt reste annulable
```

Pendant le délai, « annule l'extinction » interrompt la commande système.

## 2. Choisir une méthode de réveil

| Méthode | Prérequis | Remarque |
|---|---|---|
| **Wake-on-LAN** | carte réseau et BIOS compatibles, généralement Ethernet filaire | méthode recommandée lorsqu'elle fonctionne depuis l'état d'arrêt visé |
| **Gestion hors bande** | matériel dédié compatible | solution la plus robuste, mais rare sur un PC grand public |
| **Prise connectée** | BIOS capable de démarrer au retour du courant + prise à contrôle local | solution de secours ; ne jamais couper un PC allumé ou en veille |
| **Démarrage manuel** | aucun | reste le choix le plus sûr si l'état du PC ne peut pas être vérifié |

Le réveil doit être déclenché par un appareil encore allumé : téléphone, autre
ordinateur, serveur domotique ou satellite autonome.

## 3. Configurer Wake-on-LAN

Les libellés changent selon les cartes mères et les pilotes. Les réglages courants
sont :

1. **BIOS/UEFI**
   - activer le réveil par périphérique PCIe/réseau ;
   - désactiver un éventuel mode ErP qui coupe l'alimentation de la carte réseau.
2. **Windows**
   - autoriser la carte réseau à réveiller l'ordinateur ;
   - activer « Wake on Magic Packet » ;
   - selon le matériel, désactiver le démarrage rapide si le réveil depuis S5 ne
     fonctionne pas.
3. **Réseau**
   - relever la MAC de la carte avec `getmac /v /fo list` ;
   - envoyer un magic packet depuis le même LAN vers l'adresse de broadcast du
     réseau, généralement sur le port UDP 9.

`powercfg -devicequery wake_armed` permet de vérifier quels périphériques
Windows sont autorisés à réveiller la machine.

Les adaptateurs Wi-Fi et USB ne prennent pas tous en charge le réveil après
extinction. Il faut vérifier les spécifications du matériel et tester l'état
souhaité : veille, hibernation ou arrêt complet.

## 4. Utiliser une prise connectée en dernier recours

Cette méthode s'appuie sur l'option BIOS souvent appelée **Restore on AC Power
Loss**, **AC Back** ou **After Power Failure**, réglée sur **Power On**.

Exigences recommandées :

- prise dédiée uniquement au PC, pas à l'ensemble des périphériques ;
- API locale ou intégration domotique documentée ;
- état et commandes accessibles sans dépendre exclusivement d'un cloud ;
- réservation DHCP si l'intégration utilise une adresse IP locale ;
- alimentation laissée active pendant le fonctionnement normal.

### Avertissement critique

Couper l'alimentation d'un PC allumé, en veille ou en hibernation peut corrompre
les données. Une absence de réponse au ping **ne prouve pas** que le PC est éteint :
un pare-feu, une panne réseau ou la veille peuvent produire le même résultat.

Une future intégration automatique devra donc utiliser une vérification d'état
plus robuste qu'un ping isolé et demander une confirmation avant tout cycle
d'alimentation. En attendant, le cycle OFF/ON reste une opération manuelle à
effectuer seulement après avoir constaté l'arrêt complet.

## 5. Procédure de test

1. Tester d'abord l'extinction Jarvis et son annulation.
2. Vérifier que le PC est complètement arrêté.
3. Tester la méthode de réveil retenue indépendamment de Jarvis.
4. Pour une prise connectée, vérifier le réglage BIOS avec une coupure contrôlée
   uniquement lorsque le système est déjà arrêté.
5. Documenter localement les paramètres propres à l'installation ; ne jamais
   versionner MAC, IP privée, identifiants de compte ou nom d'appareil personnel.

## 6. Intégration future

Le code ne fournit pas encore d'adaptateur générique de prise connectée. Une future
implémentation devra :

- définir une interface indépendante du fabricant ;
- garder les identifiants dans `config.yaml`, jamais dans le dépôt ;
- rester locale et non exposée à Hermes/MCP ;
- séparer la lecture de consommation du contrôle d'alimentation ;
- conserver une confirmation forte et une vérification d'état robuste.
