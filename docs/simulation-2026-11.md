# Rapport de simulation — novembre 2026 (généré)

> **Simulation exploratoire, non validable** : aucun contrat, aucune disponibilité complète ni congé fournis. Outil d'aide à la décision, pas un conseil juridique ; validation par un spécialiste du droit suisse requise.

- Statut : **partiellement_couvert** — mode : **simulation_exploratoire** — validable : **False**
- Durée de calcul : 13.479 s — violations dures détectées par le vérificateur : 0
- Budget total déclaré : 1752 h ; planifié : 1704 h

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
| Abdu | 200 |
| Mila | 192 |
| Sahra | 192 |
| Jane | 136 |
| Zaki | 104 |
| Michael | 104 |
| Florian | 104 |
| Adam | 104 |
| Kristina | 104 |
| Sabrina | 104 |
| Simona D | 104 |
| Ying | 88 |
| Aziza | 72 |
| Chloé | 48 |
| Yasmine | 32 |
| Valérie | 16 |

## Dimanches (Ploom uniquement)

- 7 shifts par dimanche × 5 dimanches (2026-11-01, 2026-11-08, 2026-11-15, 2026-11-22, 2026-11-29) = **35 shifts** (GVA3 15, Pilar 10, GVA9 10).
- Réservés (quotas « objectif exact ») : 0 ; planifiés : 35 ; non planifiés : 0 ; restant à attribuer : 35.

## Données manquantes et hypothèses

- **CONTRACT_MISSING** (warning) : Contrat non renseigné pour 17 collaborateur(s) : Mila, Abdu, Sabrina, Kristina, Florian, Sahra, Zaki, Simona D, Yasmine, Michael, Adam, Valérie, Pierre, Aziza, Ying, Chloé, Jane. Aucun taux d'activité ni plafond n'est supposé ; le résultat est une simulation exploratoire.
- **AVAILABILITY_INCOMPLETE** (warning) : Disponibilités non déclarées (considérées ouvertes hors indisponibilités connues) pour : Mila, Abdu, Sabrina, Kristina, Florian, Sahra, Zaki, Simona D, Michael, Adam, Valérie, Pierre, Aziza, Ying, Chloé, Jane.
- **LEAVES_MISSING** (warning) : Aucun congé ni absence saisi pour la période.
- **BRAND_REQUIREMENTS_MISSING** (blocking) : Lindt : budget de 64 h sans jours ni horaires définis. Ces heures ne peuvent pas être planifiées définitivement (rien n'a été inventé).
- **BRAND_REQUIREMENTS_MISSING** (blocking) : Toblerone : budget de 64 h sans jours ni horaires définis. Ces heures ne peuvent pas être planifiées définitivement (rien n'a été inventé).
- **WEEK_BOUNDARY_HISTORY_MISSING** (warning) : Limites hebdomadaires de jours (Ying) : les semaine du 26/10 et semaine du 30/11 chevauchent une autre période et aucun planning voisin n'est fourni ; seuls les jours de la période sont comptés (jours hors période non supposés).
- **BRAND_BUDGET_MISSING** (warning) : Ploom Pilar : shifts planifiés sans budget horaire saisi ; ses heures ne sont comptées dans aucun budget (rien n'a été supposé).
- **SUNDAY_QUOTAS** (info) : 35 shift(s) du dimanche restent à distribuer : le moteur les répartira entre les collaborateurs sans quota.
- **LEGAL_REVIEW** (warning) : Règles exécutées, comme valeurs de référence à faire valider : repos quotidien, jours consécutifs. Non exécutées : durée maximale hebdomadaire (règle à activer dans le référentiel juridique), pauses légales (règle à activer dans le référentiel juridique), travail de nuit, travail du dimanche et repos compensatoires, jeunes travailleurs, catégories particulières de travailleurs, dérogations conventionnelles. Non commercialisable / non utilisable en production tant que ces règles ne sont pas exécutées et validées par un spécialiste du droit suisse.
- **HYPOTHESIS** (warning) : HYPOTHÈSE NON VALIDÉE — collaborateurs sans marque indiquée (Mila, Abdu, Sabrina, Kristina, Florian, Simona D, Yasmine, Michael, Adam) : supposés éligibles Ploom uniquement (GVA3, GVA9 et Pilar) ; Aziza : chocolat (Cailler, Lindt, Toblerone) uniquement.
- **HYPOTHESIS** (warning) : HYPOTHÈSE NON VALIDÉE — Ploom Pilar : seuls les 2 shifts du dimanche sont fournis ; besoins hors dimanche et budget non fournis.
- **HYPOTHESIS** (warning) : HYPOTHÈSE NON VALIDÉE — poids d'attribution : 1.25 pour Sahra, Mila, Abdu ; 0.75 pour Yasmine ; valeurs de paramétrage, pas des contrats.
- **HYPOTHESIS** (warning) : HYPOTHÈSE NON VALIDÉE — un seul collaborateur par shift (effectif requis = 1) ; aucun historique avant le 1er novembre.

## Préférences

| Préférence | Satisfaites | Non satisfaites |
|---|---:|---:|
| Chloé:horaire_prefere | 6 | 0 |
| Florian:tag_prefere:close | 13 | 0 |
| Kristina:tag_prefere:close | 13 | 0 |
| Mila:horaire_prefere | 24 | 0 |
| Mila:tag_prefere:open | 24 | 0 |
| Sahra:start<=10:00 | 24 | 0 |
| Simona D:horaire_prefere | 13 | 0 |
| Ying:horaire_prefere | 11 | 0 |
| Zaki:start<=10:00 | 13 | 0 |
| decalage_cosmetique | 13 | 0 |
| famille:Abdu/Mila | 22 | 0 |

## Objectifs (coût pondéré) et poids utilisés

| Terme | Coût | Poids |
|---|---:|---:|
| fatigue | 6 | 6 |
| rest_days | 0 | 40 |
| coverage | 0 | 1000 |
| budget | 0 | 800 |
| reinforce | 0 | 12 |
| preference | 0 | 10 |
| fairness | 3153 | 3 |
| site_change | 0 | 6 |
| balance | 176 | 4 |
| family | 0 | 15 |
| individual | 2304 | 1 |
| sunday_balance | 24 | 6 |
| days_balance | 75 | 3 |
| alternation | 0 | 3 |
| stagger | 0 | 10 |

Conflits chevauchement/repos évités par le modèle : {'conflits_chevauchement_repos': 8126}
