# Mesures de performance du moteur

Produites par `scripts/ops/perf_engine.sh` (tests marqués « perf »). Les tests de correction, eux, ne dépendent pas de la charge de la machine (vérifié sous charge : voir `docs/suivi-wfm.md`).

| Date | Commit | Machine | Charge avant | Conditions | Versions | Résultat | Durées |
|---|---|---|---|---|---|---|---|
| 17/11/2026 17:44 | e2a248a+modifs | Apple M4, 10 cœurs, 16 Go | 1.81 | conformes | Python 3.12.10, OR-Tools 9.15.6755 | 1 passed, 136 deselected in 46.28s | test_performance_grand_effectif 46.08 s |
