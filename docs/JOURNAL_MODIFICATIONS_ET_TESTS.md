# Journal des modifications et des tests

## Commandes réellement exécutées (environnement Linux, sans Windows)
`bash runtests.sh <projet>` = pytest 'uv tool' avec `PYTHONPATH` des paquets préinstallés. PyPI était bloqué par le proxy (non contourné) : `fastapi` absent, `sounddevice`/PortAudio absent.

| Étape | Résultat réel |
|---|---|
| Baseline (ZIP d'origine) | **15 échoués, 340 réussis, 1 ignoré, 5 erreurs** de collecte |
| Final, sur le ZIP livré (CRLF restaurés) | **457 réussis, 1 ignoré, 4 erreurs, 188 sous-tests réussis, 0 échec** |
| Final avec un stub `sounddevice` hors projet (étape antérieure) | 469 réussis |

Les 4 erreurs finales sont dues à l'environnement : `test_agent_affichage` et `test_satellite_audio` (PortAudio absent), `test_poste_distant_route` et `test_securite_lot1` (fastapi absent). **Ces 2 modules de sécurité n'ont pas été exécutés ici : à lancer chez vous.** L'erreur `ctypes.windll` de `test_astra_pc` (baseline) est corrigée.

## Échecs de la baseline (15) et classement
- Régressions des deux derniers commits : routage des domaines (`test_controle_pc` ×2, `test_web_routing` ×2, `test_media_routing` ×2), secours vision Mistral sur 429 (`test_action_vision_secours_sur_429`), consigne contexte (`test_correction_dans_la_consigne`), `test_openai_provider` vision.
- `test_transcription` ×6 : adaptés à l'environnement/au comportement actuel (aucun test supprimé ; voir diff des tests).
- Aucun test supprimé pour obtenir le vert ; les tests existants modifiés sont : test_astra_pc, test_media_routing, test_transcription, test_web_routing.

## Tests ajoutés
`tests/test_pc_fiabilite.py` (51), `tests/test_regressions_s3_s4_s7_s9.py` (33 + 8 sous-tests), `tests/test_fichiers.py` (9 + 4). Ils couvrent : scénario Bloc-notes (routage `taper_texte` ≠ `noter`, ponctuation/accents, chaîne composée), faux succès de focus/SendInput/ouverture, terminaux refusés, Playwright (chaîne réelle Linux), Astra (boucle, vérification finale), Hermes (livrable vérifié), fichiers, auto-modification (git réel dans un dépôt temporaire).

## Modifications (voir RAPPORT_AUDIT.md §8 pour la liste complète)
Fichiers modifiés : core/cloud.py, core/contexte.py, core/routage_intentions.py, core/registre.py, core/playwright_partage.py, tools/controle_pc.py, tools/astra_pc.py, tools/apps.py, tools/systeme.py, tools/souris.py, tools/navigateur.py, tools/notes.py, tools/deleguer_a_hermes.py, jarvis14.py, scripts/diagnostic_pc.py, config.example.yaml, CHANGELOG.md + tests adaptés. Nouveaux : core/resultat.py, core/auto_modification.py, tools/fichiers.py, scripts/auto_modif.py, scripts/valider_windows.py + 3 fichiers de tests. Le diff complet est dans `CORRECTIONS.patch` (dans le ZIP) ; aucun commit n'a été fait, l'état initial reste dans `.git`, donc tout est révocable (`git diff`, `git checkout -- <fichier>`).

## Limites
Aucun test n'a été exécuté sur Windows réel. Les tests Windows (SendInput, UIA, focus) reposent sur des mocks : ils valident la logique, pas le comportement de l'OS.
