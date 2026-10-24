# Plan de correction Jarvis — état après intervention

Les critères de validation d'origine (PDF `JARVIS_PLAN_CORRECTION.pdf`) restent en vigueur ; ce tableau indique ce qui a été fait et ce qui reste à valider. Détails : RAPPORT_AUDIT.md.

| § | Sujet | Statut | Corrigé (fichiers) | Reste à valider (critère du PDF) |
|---|---|---|---|---|
| S1 | Diagnostic Windows / UIA | Corrigé mais non vérifiable ici | controle_pc.py (fenêtres cloaked, DPI, focus vérifié), diagnostic_pc.py (trace HWND/exe/titre) | Lancer `diagnostic_pc.py` sur Windows : fenêtres, fenêtre active, Menu Démarrer, UIA tous OK |
| S2 | Souris / clavier | Corrigé mais non vérifiable | controle_pc.py (SendInput vérifié, UTF-16, curseur ±3 px), souris.py | `valider_windows.py --actions-reelles` : texte exact tapé dans le Bloc-notes |
| S3 | Chrome / Playwright | Corrigé et testé (Linux) | playwright_partage.py, navigateur.py, diagnostic_pc.py | Sur Windows : ligne « Playwright » OK ; cause racine Windows non établie |
| S4 | Astra | Corrigé et testé (mocks) | astra_pc.py, cloud.py | Une vraie tâche vision ; pas d'annonce « terminé » avant vérification |
| S5 | Fichiers / applications | Fichiers testés ; applications non vérifiables | fichiers.py, apps.py, systeme.py, controle_pc.py | Ouvrir Chrome, VS Code, Bloc-notes sur Windows sans faux « non ouvert » |
| S6 | Routage vocal | Partiellement corrigé | routage_intentions.py, contexte.py, controle_pc.py, notes.py, jarvis14.py | Mesure du routage LLM réel sur les 4 phrases prioritaires |
| S7 | Hermes | Corrigé et testé (mocks) | deleguer_a_hermes.py | Test avec un vrai Hermes |
| S8 | Orchestration | Partiellement corrigé | enchainer_commandes (arrêt sur échec, injection de fenêtre), resultat.py | Scénario « ouvre le Bloc-notes, écris, enregistre » sur Windows |
| S9 | Auto-modification | Corrigé et testé (git réel) | auto_modification.py, auto_modif.py, registre.py | Branchement vocal non fait volontairement |
| S10 | Recette finale | Partiellement corrigé | valider_windows.py | Exécution sur votre PC et renvoi du JSON |

Protocole : suivre INSTRUCTIONS_WINDOWS_UV.md, étapes 4 à 6, puis renvoyer le JSON. Tant qu'il n'est pas validé, le projet n'est **pas** déclaré entièrement corrigé.
