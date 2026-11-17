# Évaluation du moteur de planification : OR-Tools CP-SAT ou Timefold

État au 17 novembre 2026. Mesures reproductibles : `PYTHONPATH=packages/solver .venv/bin/python packages/solver/bench/bench_engine.py 30`.

## Moteur actuel

- Solveur : **OR-Tools CP-SAT** (Apache 2.0, gratuit, sans licence ni service externe), intégré en Python dans `packages/solver`.
- Une variable de décision par affectation **admissible**. Les affectations impossibles sont écartées avant le calcul.
- **Contraintes obligatoires** = contraintes du modèle. Elles ne sont jamais échangées contre un meilleur score.
- **Préférences** = coûts pondérés.
- **Optimisation hiérarchisée**, dans un ordre explicite. Chaque niveau est figé avant le suivant :
  1. couverture ;
  2. engagements ;
  3. optimisation.
- Verrous respectés. Réoptimisation complète, partielle ou locale, avec un coût de stabilité qui limite les changements.
- Simulations par stratégies, comparées sur la couverture, l'équité, les préférences, le coût et les changements.
- **Vérificateur indépendant**, en Python pur sans CP-SAT, exécuté à trois moments :
  - après le calcul ;
  - sur les données relues ;
  - sur le planning enregistré.
- **Statuts distingués** :

  | Statut | Signification |
  |---|---|
  | `optimal` | optimalité prouvée à chaque niveau |
  | `faisable` | solution valide, optimalité non prouvée |
  | `partiellement_couvert` | shifts non couverts, listés |
  | `infaisable` | impossibilité prouvée, avec diagnostic |
  | `interrompu` | délai atteint sans solution ; ce n'est **pas** une preuve d'impossibilité |
  | erreur technique | statut d'exécution distinct |

## Mesures (instances synthétiques à graine fixe, 30 jours, limite 30 s, 8 threads, plafond 176 h, jours min/max)

Toutes les tailles ont donné 0 violation et 100 % de couverture. La mémoire est le pic du processus.

| Collaborateurs | Shifts | Variables | 1re solution valide | Statut | Mémoire |
|---|---|---|---|---|---|
| 30 | 360 | 9 720 | 0,9 s | optimal (prouvé en 14 s) | 0,8 Go |
| 60 | 900 | 29 160 | 3,5 s | faisable | 1,7 Go |
| 100 | 1 440 | 48 600 | 6,4 s | faisable | 2,2 Go |
| 150 | 2 160 | 72 900 | 9,6 s | faisable | 2,4 Go |

**Observation** : à 150 collaborateurs, le niveau « engagements » n'a pas trouvé de solution dans sa part de temps (5 s). Ses critères ont été reportés au niveau suivant ; ils ne sont jamais oubliés.

**Pistes** : partager le temps selon la taille et préférer une recherche à large voisinage (LNS) à partir de la solution précédente. La démo réelle (29 collaborateurs) relève du premier cas.

## Timefold

- **Solver Java/Kotlin** : métaheuristiques (recherche locale) et score incrémental. Très efficace sur les grands problèmes.
  - L'édition Community est sous licence Apache 2.0.
  - L'édition **Enterprise**, nécessaire en production pour le calcul multi-thread et la sélection de voisinage, est **payante**.
- **Python** : le solver Python officiel a été **arrêté en 2025** et son dépôt archivé ; il reste un fork communautaire (SolverForge). L'adopter imposerait :
  - soit un service Java séparé (nouvelle pile, déploiement, maintenance) ;
  - soit une dépendance communautaire non soutenue par l'éditeur.
- **Recherche locale** : elle donne de bonnes solutions rapidement mais **ne prouve ni l'optimalité ni l'impossibilité**. Or ces deux preuves sont des exigences du produit : distinguer « impossible » de « délai atteint » et expliquer les blocages.

## Décision

**Conserver OR-Tools CP-SAT et améliorer son modèle.** Raisons :

1. Les mesures montrent une solution valide en moins de 10 s jusqu'à 150 collaborateurs, avec une couverture complète.
2. CP-SAT prouve l'impossibilité, ce qui fournit le noyau des contraintes en cause pour les diagnostics, et prouve l'optimalité sur les petits cas.
3. Aucun coût de licence, la même pile Python que l'API, aucun service supplémentaire à exploiter.

Une migration vers Timefold Java ne serait reconsidérée que si des mesures sur des données réelles plus grandes, au-delà de 300 collaborateurs ou sur plusieurs mois, montraient des limites que la LNS de CP-SAT ne résout pas.

## Sources

- [Timefold Solver (GitHub)](https://github.com/TimefoldAI/timefold-solver)
- [Éditions commerciales Timefold](https://docs.timefold.ai/timefold-solver/latest/commercial-editions/commercial-editions)
- [Édition Enterprise](https://docs.timefold.ai/timefold-solver/latest/enterprise-edition/enterprise-edition)
- [Timefold 1.25.0, solver Python déplacé (12 août 2025)](https://timefold.pages.dev/releases/timefold-solver-1-25-0)
- [SolverForge, fork du solver Python arrêté](https://pypi.org/project/solverforge-legacy/)
