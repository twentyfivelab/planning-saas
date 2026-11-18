# Mesures de performance du moteur

Produites par `scripts/ops/perf_engine.sh` (tests marqués « perf »). Les tests de correction, eux, ne dépendent pas de la charge de la machine (vérifié sous charge : voir `docs/suivi-wfm.md`).

## Durée maximale et temps réellement mesurés (18/11/2026)

Mesure sur l'instance de référence (150 collaborateurs, 2 160 shifts, durée maximale 45 s), machine au repos :

| Étape | Temps mesuré | Comptée dans la durée maximale ? |
|---|---|---|
| Construction du modèle | 3,8 s | oui |
| Recherche du solveur (3 niveaux : 6,0 s + 8,7 s + 25,5 s, et 1,4 s de passage entre niveaux) | 41,6 s | oui |
| Dépassement en fin de recherche (le solveur termine l'étape en cours) | 0,4 s | au-delà |
| Contrôles du moteur après la recherche (vérificateur indépendant, coûts, indicateurs) | 0,65 s | non, en plus |
| **Appel complet du moteur** | **46,1 s** | |

Les « 46 s pour 45 s » s'expliquent donc par 0,4 s de dépassement du solveur et 0,65 s de contrôles. Dans l'application s'ajoutent la préparation des données (avant) et l'enregistrement vérifié (après) ; chaque calcul enregistre désormais ces temps (`timing` du calcul) et l'écran de résultat les affiche. Le libellé de la durée maximale a été précisé en conséquence.

## Relevés

| Date | Commit | Machine | Charge avant | Conditions | Versions | Résultat | Durées |
|---|---|---|---|---|---|---|---|
| 17/11/2026 17:44 | e2a248a+modifs | Apple M4, 10 cœurs, 16 Go | 1.81 | conformes | Python 3.12.10, OR-Tools 9.15.6755 | 1 passed, 136 deselected in 46.28s | test_performance_grand_effectif 46.08 s |
| 17/11/2026 18:29 | b9fed88 | Apple M4, 10 cœurs, 16 Go | 1.98 | conformes | Python 3.12.10, OR-Tools 9.15.6755 | 1 passed, 136 deselected in 46.50s | test_performance_grand_effectif 46.09 s |
