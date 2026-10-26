# Rapport de simulation — novembre 2026 (généré)

> **Simulation exploratoire, non validable** : aucun contrat, aucune disponibilité complète ni congé fournis. Outil d'aide à la décision, pas un conseil juridique ; validation par un spécialiste du droit suisse requise.

- Statut : **partiellement_couvert** — mode : **simulation_exploratoire** — validable : **False**
- Durée de calcul : 1.298 s — violations dures détectées par le vérificateur : 0
- Budget total déclaré : 1752 h ; planifié : 1624 h

## Budgets (heures effectives)

| Marque | Budget | Planifié | Restant | Besoins définis |
|---|---:|---:|---:|---|
| Ploom GVA3 | 720 | 720 | 0 | oui |
| Ploom GVA9 | 480 | 480 | 0 | oui |
| Cartier | 64 | 64 | 0 | oui |
| Valmont | 136 | 136 | 0 | oui |
| Cellcosmet | 68 | 68 | 0 | oui |
| Nuxe | 68 | 68 | 0 | oui |
| Cailler | 88 | 88 | 0 | oui |
| Lindt | 64 | 0 | 64 | **non — à renseigner** |
| Toblerone | 64 | 0 | 64 | **non — à renseigner** |

## Heures par collaborateur

| Collaborateur | Heures effectives |
|---|---:|
| Jane | 136 |
| Sahra | 128 |
| Abdu | 128 |
| Mila | 128 |
| Simona D | 112 |
| Sabrina | 104 |
| Adam | 104 |
| Kristina | 104 |
| Zaki | 104 |
| Michael | 104 |
| Florian | 104 |
| Ying | 96 |
| Valérie | 96 |
| Pierre | 80 |
| Chloé | 40 |
| Yasmine | 32 |
| Aziza | 24 |

## Données manquantes et hypothèses

- **CONTRACT_MISSING** (warning) : Contrat non renseigné pour 17 collaborateur(s) : Mila, Abdu, Sabrina, Kristina, Florian, Sahra, Zaki, Simona D, Yasmine, Michael, Adam, Valérie, Pierre, Aziza, Ying, Chloé, Jane. Aucun taux d'activité ni plafond n'est supposé ; le résultat est une simulation exploratoire.
- **AVAILABILITY_INCOMPLETE** (warning) : Disponibilités non déclarées (considérées ouvertes hors indisponibilités connues) pour : Mila, Abdu, Sabrina, Kristina, Florian, Sahra, Zaki, Simona D, Michael, Adam, Valérie, Pierre, Aziza, Ying, Chloé, Jane.
- **LEAVES_MISSING** (warning) : Aucun congé ni absence saisi pour la période.
- **BRAND_REQUIREMENTS_MISSING** (blocking) : Lindt : budget de 64 h sans jours ni horaires définis. Ces heures ne peuvent pas être planifiées définitivement (rien n'a été inventé).
- **BRAND_REQUIREMENTS_MISSING** (blocking) : Toblerone : budget de 64 h sans jours ni horaires définis. Ces heures ne peuvent pas être planifiées définitivement (rien n'a été inventé).
- **LEGAL_REVIEW** (warning) : Seuls le repos quotidien (défaut 11 h) et le maximum de jours consécutifs (défaut 6) sont exécutés, comme valeurs de référence NON validées juridiquement. Non exécutées : pauses légales, durée maximale du travail (journalière/hebdomadaire), travail de nuit, travail du dimanche, jeunes travailleurs, catégories particulières de travailleurs, dérogations conventionnelles. Non commercialisable / non utilisable en production tant que ces règles ne sont pas exécutées et validées par un spécialiste du droit suisse.
- **HYPOTHESIS** (warning) : HYPOTHÈSE NON VALIDÉE — horaires Nuxe/Cellcosmet : mêmes modèles que Valmont (08-17, 09-18, 10-19), non fournis.
- **HYPOTHESIS** (warning) : HYPOTHÈSE NON VALIDÉE — horaire Cailler : 09:00-18:00 (1 h de pause), non fourni.
- **HYPOTHESIS** (warning) : HYPOTHÈSE NON VALIDÉE — collaborateurs sans marque indiquée (Mila, Abdu, Sabrina, Kristina, Florian, Simona D, Yasmine, Michael, Adam) : supposés éligibles Ploom uniquement ; Aziza : chocolat (Cailler, Lindt, Toblerone) uniquement.
- **HYPOTHESIS** (warning) : HYPOTHÈSE NON VALIDÉE — poids d'attribution : 1.25 pour Sahra, Mila, Abdu ; 0.75 pour Yasmine ; valeurs de paramétrage, pas des contrats.
- **HYPOTHESIS** (warning) : HYPOTHÈSE NON VALIDÉE — un seul collaborateur par shift (effectif requis = 1) ; aucun historique avant le 1er novembre.

## Préférences

| Préférence | Satisfaites | Non satisfaites |
|---|---:|---:|
| Chloé:horaire_prefere | 5 | 0 |
| Florian:tag_prefere:close | 13 | 0 |
| Kristina:tag_prefere:close | 13 | 0 |
| Mila:horaire_prefere | 16 | 0 |
| Mila:tag_prefere:open | 16 | 0 |
| Sahra:start<=10:00 | 16 | 0 |
| Simona D:horaire_prefere | 14 | 0 |
| Ying:horaire_prefere | 12 | 0 |
| Zaki:start<=10:00 | 13 | 0 |
| decalage_cosmetique | 14 | 0 |
| famille:Abdu/Mila | 6 | 0 |

## Objectifs (coût pondéré) et poids utilisés

| Terme | Coût | Poids |
|---|---:|---:|
| fatigue | 0 | 6 |
| rest_days | 0 | 40 |
| coverage | 0 | 1000 |
| budget | 0 | 800 |
| reinforce | 1344 | 12 |
| preference | 0 | 10 |
| fairness | 1527 | 3 |
| site_change | 0 | 6 |
| balance | 136 | 4 |
| family | 0 | 15 |
| stagger | 0 | 10 |

Conflits chevauchement/repos évités par le modèle : {'conflits_chevauchement_repos': 8145}

## Limites de ce rapport
Rapport généré par `packages/solver/scripts/simulate.py` (poids par défaut, 60 s max). Les hypothèses non validées ci-dessus doivent être confirmées ; les 128 h Lindt/Toblerone restent non planifiées faute de jours et horaires. Application non commercialisable en l'état (règles légales suisses non exécutées, voir `docs/limits-and-next-steps.md`).
