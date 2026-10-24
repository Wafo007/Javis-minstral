# Installation et exécution sous Windows 11 avec uv

Dans PowerShell, à la racine du projet décompressé (`Javis-minstral`).

```powershell
# 1. Dépendances
uv sync
uv run playwright install chromium

# 2. Configuration (ne jamais partager config.yaml)
copy config.example.yaml config.yaml     # puis renseigner vos clés dans config.yaml uniquement

# 3. Tests (les 2 modules fastapi ne tournent que si fastapi est installé : ils le seront après uv sync)
uv run pytest -q

# 4. Diagnostic du contrôle du PC (aucune action destructrice)
uv run python scripts/diagnostic_pc.py

# 5. Validation Windows (lecture seule, sans frappe ni clic réels)
uv run python scripts/valider_windows.py

# 6. Validation complète : scénario Bloc-notes réel (ouvre le Bloc-notes, tape, clique, écrit un fichier)
#    Ne laissez ni souris ni clavier pendant l'exécution.
uv run python scripts/valider_windows.py --actions-reelles
#    Facultatif : exiger Chrome / VS Code / Explorateur ouverts
uv run python scripts/valider_windows.py --actions-reelles --exiger-fenetres

# 7. Lancement
uv run python jarvis14.py
```

## Playwright : erreur `_greenlet` / DLL
Installer le redistribuable Microsoft Visual C++ 2015-2022 (x64), puis :
`uv sync --reinstall-package greenlet --reinstall-package playwright`, et relancer `diagnostic_pc.py` (ligne « Playwright » : la chaîne complète doit être OK).

## Nouvelles clés de config (voir config.example.yaml)
`controle_pc.autoriser_terminal` (false par défaut : Jarvis refuse de taper dans un terminal), `astra_pc.verification_finale`, `cloud.secours_actif`.

## Auto-modification encadrée (non branchée à la voix)
```powershell
uv run python scripts/auto_modif.py demarrer <nom>   # branche jarvis/auto-...
uv run python scripts/auto_modif.py diff
uv run python scripts/auto_modif.py valider          # lance les tests
uv run python scripts/auto_modif.py enregistrer "message"
uv run python scripts/auto_modif.py annuler          # rollback
uv run python scripts/auto_modif.py terminer
```
Aucune fusion automatique : relire la branche avant de fusionner.

## Ce que je vous demande de renvoyer
Le fichier JSON produit par `valider_windows.py --actions-reelles` (indiqué en fin d'exécution) et le résultat de `uv run pytest -q`. Ne renvoyez pas config.yaml ni vos clés.
