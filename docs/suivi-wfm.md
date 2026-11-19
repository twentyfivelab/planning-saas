# Suivi du programme WFM : état réel

Mise à jour : 18 novembre 2026.

Une fonctionnalité n'est classée « terminée et vérifiée » que si une vérification exécutée la couvre. Les autres sont « partielles » (utilisables, avec des limites) ou « restantes ». Documents liés :
- `docs/moteur-evaluation.md` (choix du moteur, mesures) ;
- `docs/identite-visuelle.md` (rose de référence) ;
- `docs/backup-restore.md`.

## Résultats de tests (19/11/2026)

| Suite | Résultat | Environnement |
|---|---|---|
| Moteur, tests de correction (`packages/solver`) | **142 / 142** (19/11, dont 5 tests d'équité des heures) | local ; aussi **127 / 127 sous forte charge** (charge moyenne 44 sur 10 cœurs) et pendant la suite e2e |
| Moteur, mesures de performance (marqueur `perf`) | à part : `scripts/ops/perf_engine.sh` | conditions consignées dans `docs/mesures-moteur.md` |
| API (`apps/api`) | **191 / 191** | base PostgreSQL jetable par session (`planning_test_<pid>`) |
| Interface, unitaires, dont contrastes WCAG AA | **124 / 124** | Vitest |
| Navigateur e2e | **90 / 90** (suite complète, seule ; le 19/11 aussi 85 / 85 en parallèle de la suite API, charge jusqu'à 16) | pile Docker isolée (`infra/compose.e2e.yaml`, base `planning_e2e`) |
| ruff, TypeScript, ESLint | sans erreur | |

Fiabilité du moteur (deux échecs observés sous charge, corrigés à la source, sans relance ni délai allongé) :
- **Premier niveau abandonné trop tôt** : sans solution ni preuve dans sa part du temps, le niveau « couverture » s'arrêtait et annonçait « interrompu » alors que le budget n'était pas épuisé. Il reçoit désormais tout le temps restant.
- **Conflit de minimums de jours dépendant du temps de calcul** : quand plusieurs collaborateurs se partagent les mêmes shifts, le conflit est un simple dénombrement. Il est maintenant signalé avant tout calcul (majorant exact, jour par jour), donc identique quelle que soit la charge. Les conflits plus subtils restent identifiés par le noyau du solveur (test dédié).
- **Couverture médiocre figée sous forte charge** (trouvé par le test d'invariant, reproduit 5 fois sur 6 avec six calculs simultanés) : un niveau non prouvé dans sa part du temps voyait sa valeur figée comme limite, si bien qu'une couverture obtenue à la hâte ne pouvait plus être améliorée. Désormais, les critères d'un niveau non prouvé restent optimisés aux niveaux suivants (toujours en priorité, par leur poids). Et un planning vide, sans preuve, alors que des affectations sont possibles, est annoncé « interrompu » (temps insuffisant) au lieu de « partiellement couvert ». Après correction : 6 sur 6 dans les mêmes conditions.
- **Correction et performance séparées** : le test du grand effectif est scindé. La partie « correction » vérifie un invariant valable quel que soit le temps (planning entièrement vérifié, ou « interrompu » sans affectation ; jamais d'optimum annoncé sans preuve). La partie « performance » (marqueur `perf`) est exclue des suites par défaut et de l'intégration continue ; elle s'exécute par `scripts/ops/perf_engine.sh`, qui refuse de mesurer sur une machine chargée et consigne les conditions.

Intermittences corrigées à la source :
- **Régénération de décembre parfois refusée (test API)** : un test précédent verrouillait un shift choisi dans la solution du moteur ; quand c'était un shift Cartier ou un shift donné à Zaki, le test suivant (Cartier désactivé, Zaki exclu) obtenait à juste titre « affectation verrouillée impossible ». Le premier test ne choisit plus ce que le second désactive.
- **« mouvement réduit »** : la lecture se faisait en deux allers-retours, et le tableau de bord, rechargé par un événement temps réel, pouvait remplacer la carte entre les deux. Un élément détaché donne une durée vide, d'où NaN. Le test lit désormais toutes les cartes en une seule exécution dans la page : 20 passages sur 20, plus les suites complètes.
- **Alignement** : la mesure se fait désormais après l'animation d'ouverture.
- **Dépendance entre tests navigateur (identifiée et corrigée, 19/11)** : le scénario « E. pondérations » recalculait NOVEMBRE avec les paramètres actuels, alors que d'autres scénarios (réaffectation, fiche modifiée, versions) lisent les affectations et les paramètres conservés de novembre ; selon l'ordre, ils voyaient un planning différent. Le scénario utilise désormais un mois dédié (juillet 2027), supprimé à la fin. Cette dépendance est réelle ; elle n'est **pas** établie comme la cause des échecs `reassign`, `team` et `wfm` observés en parallèle de la suite API (voir « Incertitudes ») : ceux-ci restent ouverts.

## Équité des heures mensuelles : analyse et correction du 19/11/2026

Analyse faite sur une **copie** de la base (`planning_copie_equite`, restaurée depuis la sauvegarde `backups/copie-equite-20261119-2009.dump`) : plannings actifs, archives et base réelle non modifiés. « Avant » = plannings réellement enregistrés (archives d'avril 2027 et de décembre 2026, planning actif de février 2027 du compte d'essai) ; « après » = même mois recalculé sur la copie avec le moteur corrigé, mêmes paramètres, 30 s.

**Cause démontrée** (rapports des générations réelles : tous les niveaux PROUVÉS optimaux, en 4 à 11 s sur 30 à 60 s — ce n'était donc pas un manque de temps)
1. **Priorité automatique par le poids d'allocation** : la cible d'équité était proportionnelle au poids, et le critère « priorité individuelle », actif par défaut, favorisait les poids les plus forts. Les poids de la démonstration (1,25 pour Sahra, Mila, Abdu ; 0,75 pour Yasmine) sont marqués « HYPOTHÈSE NON VALIDÉE » dans les données d'origine : les extrêmes observés (176 h et 24 h) correspondent exactement à ces poids.
2. **Cibles fausses** : la somme des cibles était nettement inférieure aux heures réellement distribuées (février : ≈ 1 170 h de cibles pour ≈ 1 580 h attribuées), car l'excédent des collaborateurs limités n'était pas redistribué. Au-delà de sa cible, l'écart étant compté en valeur absolue, une heure de plus coûtait autant quel que soit le collaborateur : l'équité ne départageait plus personne, et les autres critères concentraient les heures jusqu'au plafond de 176 h.
3. **Écart indifférent sous la cible** : quand plusieurs collaborateurs comparables partagent un petit volume (ex. Aziza, Hugo, Simon sur Cailler en décembre), 85 + 5 h d'écart coûtaient autant que 45 + 45 h : tout pouvait aller à l'un, rien à l'autre.
4. Unités incohérentes (cause latente, non présente dans ces données) : objectif contractuel en minutes mélangé à « poids × jours » pour les autres ; un collaborateur sans objectif aurait été poussé vers 0 h.

**Correction (moteur et évaluateur indépendant, mêmes formules)**
- Part équitable calculée par remplissage : même proportion de sa référence pour chacun (objectif contractuel s'il est renseigné, sinon jours où il peut réellement travailler × 8 h), dans sa capacité (un shift par jour, jours maximum, plafond mensuel) ; l'excédent des collaborateurs limités revient aux autres. Le poids d'allocation n'intervient plus.
- Écart progressif : au-delà de 16 h puis de 40 h d'écart, chaque heure coûte davantage ; un manque ou un surplus est réparti entre collaborateurs comparables.
- Shifts où le collaborateur n'est qu'en renfort : hors part équitable (dernier recours par définition, comme avant).
- « Priorité individuelle » désactivée par défaut (aucune priorité automatique : ancienneté, mérite) ; activable explicitement dans les pondérations. L'ancienne valeur par défaut n'est plus appliquée, même par un planning qui conserve ses paramètres (aucun planning existant n'est modifié : effet à la prochaine génération).
- Testé : poids sans effet par défaut (l'ancien moteur donnait 144 h contre 80 h à deux collaborateurs identiques), unités cohérentes, renfort hors part, manque réparti, part redistribuée, évaluateur = moteur. Essai plus fort de l'équité (×5, ×20) écarté : il réduisait la couverture des shifts optionnels sans aider les collaborateurs limités par leurs habilitations.

**Contraintes réellement bloquantes ou paramètres, et non manque de temps** : capacité individuelle (jours disponibles, jours maximum, marques autorisées), niveau d'habilitation (renfort ou secondaire seulement), volume des marques prioritaires (besoins et budgets du mois). Pierre (renfort sur toutes les marques ayant des besoins, prioritaire uniquement sur Lindt et Toblerone, sans besoin ce mois) n'est plus sollicité : si vous souhaitez qu'il fasse partie de la base, passez-le en prioritaire ou secondaire sur des marques qui ont des besoins.

**Temps de calcul** : décembre et février prouvés optimaux (4 à 7 s). Avril : à 30 s, l'optimisation est interrompue faute de temps (solution équilibrée mais non prouvée) ; preuve obtenue à 72 s avec la même répartition (seuls Aziza et Valérie, à coût égal, échangent 88 / 136 h).

**Février (compte d'essai)** : aucun budget n'est saisi ; les shifts optionnels n'ont alors aucun objectif, leur nombre dépendait de l'ancienne cible (42) et dépend maintenant de la nouvelle part équitable (30). Renseigner les budgets du mois fixe ce volume indépendamment de l'équité. Couverture des shifts obligatoires inchangée partout (100 %).

#### Avril 2027 — tenant de démonstration

- Couverture des shifts obligatoires : avant 167/167, après 167/167 — shifts optionnels attribués : avant 70/114, après 70/114 — shifts restants : avant 44, après 44
- Calcul « après » (30 s) : 30.0 s, couverture prouvé / optimisation non prouvé (temps écoulé)
- Heures des collaborateurs pouvant travailler : avant 24–176 h, après 0–160 h

| Collaborateur | Poids | Avant (planning enregistré) | Après | Capacité | Raison d'un écart persistant |
|---|---|---|---|---|---|
| Pierre C. | 1.0 | 80 h | 0 h | 176 h | renfort uniquement sur les marques qui ont des besoins ce mois (prioritaire sur : Lindt 0 shifts / 2 prioritaires, Toblerone 0 shifts / 2 prioritaires) |
| Chloé D. | 1.0 | 88 h | 64 h | 112 h | 14 jours possibles; volume limité de ses marques prioritaires (Valmont 66 shifts / 2 prioritaires) |
| Yasmine D. | 0.75 | 24 h | 80 h | 96 h | disponible L-M-M seulement; 12 jours possibles; volume limité de ses marques prioritaires (Ploom GVA3 90 shifts / 9 prioritaires, Ploom GVA9 60 shifts / 9 prioritaires, Ploom Pilar 8 shifts / 9 prioritaires) |
| Aziza M. | 1.0 | 104 h | 88 h | 176 h | volume limité de ses marques prioritaires (Cailler 26 shifts / 2 prioritaires, Lindt 0 shifts / 2 prioritaires, Toblerone 0 shifts / 2 prioritaires) |
| Ying Y. | 1.0 | 88 h | 112 h | 176 h | volume limité de ses marques prioritaires (Valmont 66 shifts / 2 prioritaires) |
| Valérie M. | 1.0 | 104 h | 136 h | 176 h | volume limité de ses marques prioritaires (Cailler 26 shifts / 2 prioritaires) |
| I Jane D. | 1.0 | 144 h | 144 h | 144 h | au maximum de ce qu'il peut faire (18 jours possibles) |
| Sahra H. | 1.25 | 176 h | 152 h | 176 h | équilibré avec les collaborateurs comparables |
| Abdu S. | 1.25 | 176 h | 160 h | 176 h | équilibré avec les collaborateurs comparables |
| Adam K. | 1.0 | 176 h | 160 h | 176 h | équilibré avec les collaborateurs comparables |
| Florian A. | 1.0 | 128 h | 160 h | 176 h | équilibré avec les collaborateurs comparables |
| Jamilatu D. | 1.25 | 176 h | 160 h | 176 h | équilibré avec les collaborateurs comparables |
| Sabrina L. | 1.0 | 120 h | 160 h | 176 h | équilibré avec les collaborateurs comparables |
| Simona D.. | 1.0 | 168 h | 160 h | 176 h | équilibré avec les collaborateurs comparables |
| Zaki Zakaria H. | 1.0 | 144 h | 160 h | 176 h | équilibré avec les collaborateurs comparables |

Aucun shift possible ce mois (aucune de leurs marques n'a de besoin) : Chloé D., Hugo S., Paul-Joseph D., Rebecca T., Selin A., Simon F., Simona A., Sylvain Z., Yanis B..

#### Décembre 2026 — tenant de démonstration

- Couverture des shifts obligatoires : avant 171/171, après 171/171 — shifts optionnels attribués : avant 71/115, après 71/115 — shifts restants : avant 44, après 44
- Calcul « après » (30 s) : 6.7 s, couverture prouvé / engagements prouvé / optimisation prouvé
- Heures des collaborateurs pouvant travailler : avant 0–128 h, après 0–104 h

| Collaborateur | Poids | Avant (planning enregistré) | Après | Capacité | Raison d'un écart persistant |
|---|---|---|---|---|---|
| Pierre C. | 1.0 | 0 h | 0 h | 176 h | renfort uniquement sur les marques qui ont des besoins ce mois (prioritaire sur : Lindt 0 shifts / 8 prioritaires, Toblerone 0 shifts / 9 prioritaires) |
| Chloé D. | 1.0 | 32 h | 24 h | 96 h | 12 jours possibles; secondaire (jamais prioritaire) sur les marques qui ont des besoins; volume limité de ses marques prioritaires (Lindt 0 shifts / 8 prioritaires, Toblerone 0 shifts / 9 prioritaires) |
| Simona A. | 1.0 | 24 h | 32 h | 64 h | 8 jours possibles; secondaire (jamais prioritaire) sur les marques qui ont des besoins; volume limité de ses marques prioritaires (Toblerone 0 shifts / 9 prioritaires) |
| Sylvain Z. | 1.0 | 40 h | 32 h | 104 h | 13 jours possibles; volume limité de ses marques prioritaires (Cailler 27 shifts / 7 prioritaires, Lindt 0 shifts / 8 prioritaires, Toblerone 0 shifts / 9 prioritaires) |
| Yasmine D. | 0.75 | 32 h | 40 h | 112 h | disponible L-M-M seulement; 14 jours possibles; volume limité de ses marques prioritaires (Ploom GVA3 93 shifts / 12 prioritaires, Ploom GVA9 62 shifts / 12 prioritaires, Ploom Pilar 8 shifts / 12 prioritaires) |
| Chloé D. | 1.0 | 72 h | 48 h | 104 h | 13 jours possibles; volume limité de ses marques prioritaires (Valmont 66 shifts / 2 prioritaires) |
| Aziza M. | 1.0 | 48 h | 56 h | 176 h | volume limité de ses marques prioritaires (Cailler 27 shifts / 7 prioritaires, Lindt 0 shifts / 8 prioritaires, Toblerone 0 shifts / 9 prioritaires) |
| Hugo S. | 1.0 | 56 h | 56 h | 176 h | volume limité de ses marques prioritaires (Cailler 27 shifts / 7 prioritaires, Lindt 0 shifts / 8 prioritaires, Toblerone 0 shifts / 9 prioritaires) |
| Simon F. | 1.0 | 8 h | 56 h | 176 h | volume limité de ses marques prioritaires (Cailler 27 shifts / 7 prioritaires, Lindt 0 shifts / 8 prioritaires, Toblerone 0 shifts / 9 prioritaires) |
| Valérie M. | 1.0 | 96 h | 56 h | 176 h | volume limité de ses marques prioritaires (Cailler 27 shifts / 7 prioritaires) |
| Zaki Zakaria H. | 1.0 | 56 h | 64 h | 152 h | 19 jours possibles; volume limité de ses marques prioritaires (Cartier 8 shifts / 2 prioritaires, Ploom GVA3 93 shifts / 12 prioritaires, Ploom GVA9 62 shifts / 12 prioritaires, Ploom Pilar 8 shifts / 12 prioritaires) |
| I Jane D. | 1.0 | 112 h | 72 h | 136 h | 17 jours possibles; volume limité de ses marques prioritaires (Cellcosmet 22 shifts / 1 prioritaires, Nuxe 22 shifts / 1 prioritaires) |
| Jamilatu D. | 1.25 | 112 h | 88 h | 176 h | équilibré avec les collaborateurs comparables |
| Paul-Joseph D. | 1.0 | 80 h | 88 h | 176 h | équilibré avec les collaborateurs comparables |
| Rebecca T. | 1.0 | 64 h | 96 h | 176 h | secondaire (jamais prioritaire) sur les marques qui ont des besoins |
| Selin A. | 1.0 | 72 h | 96 h | 176 h | secondaire (jamais prioritaire) sur les marques qui ont des besoins |
| Ying Y. | 1.0 | 104 h | 96 h | 176 h | équilibré avec les collaborateurs comparables |
| Abdu S. | 1.25 | 128 h | 104 h | 176 h | équilibré avec les collaborateurs comparables |
| Adam K. | 1.0 | 96 h | 104 h | 176 h | équilibré avec les collaborateurs comparables |
| Anastasia A. | 1.0 | 96 h | 104 h | 176 h | équilibré avec les collaborateurs comparables |
| Florian A. | 1.0 | 96 h | 104 h | 176 h | équilibré avec les collaborateurs comparables |
| Kristina T. | 1.0 | 96 h | 104 h | 176 h | équilibré avec les collaborateurs comparables |
| Sabrina L. | 1.0 | 96 h | 104 h | 176 h | équilibré avec les collaborateurs comparables |
| Sahra H. | 1.25 | 128 h | 104 h | 176 h | équilibré avec les collaborateurs comparables |
| Simona D.. | 1.0 | 96 h | 104 h | 176 h | équilibré avec les collaborateurs comparables |
| Yanis B. | 1.0 | 96 h | 104 h | 176 h | équilibré avec les collaborateurs comparables |

#### Février 2027 — compte d’essai

- Couverture des shifts obligatoires : avant 156/156, après 156/156 — shifts optionnels attribués : avant 42/104, après 30/104 — shifts restants : avant 62, après 74
- Calcul « après » (30 s) : 4.6 s, couverture prouvé / optimisation prouvé
- Heures des collaborateurs pouvant travailler : avant 24–176 h, après 0–112 h

| Collaborateur | Poids | Avant (planning enregistré) | Après | Capacité | Raison d'un écart persistant |
|---|---|---|---|---|---|
| Pierre | 1.0 | 72 h | 0 h | 176 h | renfort uniquement sur les marques qui ont des besoins ce mois (prioritaire sur : Lindt 0 shifts / 2 prioritaires, Toblerone 0 shifts / 2 prioritaires) |
| Chloé | 1.0 | 56 h | 40 h | 96 h | 12 jours possibles; volume limité de ses marques prioritaires (Valmont 60 shifts / 2 prioritaires) |
| Jane | 1.0 | 64 h | 48 h | 128 h | 16 jours possibles; volume limité de ses marques prioritaires (Cellcosmet 20 shifts / 1 prioritaires, Nuxe 20 shifts / 1 prioritaires) |
| Yasmine | 0.75 | 24 h | 56 h | 96 h | disponible L-M-M seulement; 12 jours possibles; volume limité de ses marques prioritaires (Ploom GVA3 84 shifts / 11 prioritaires, Ploom GVA9 56 shifts / 11 prioritaires, Ploom Pilar 8 shifts / 11 prioritaires) |
| Ying | 1.0 | 72 h | 64 h | 176 h | volume limité de ses marques prioritaires (Valmont 60 shifts / 2 prioritaires) |
| Aziza | 1.0 | 72 h | 80 h | 176 h | volume limité de ses marques prioritaires (Cailler 24 shifts / 2 prioritaires, Lindt 0 shifts / 2 prioritaires, Toblerone 0 shifts / 2 prioritaires) |
| Valérie | 1.0 | 72 h | 80 h | 176 h | volume limité de ses marques prioritaires (Cailler 24 shifts / 2 prioritaires) |
| Abdu | 1.25 | 176 h | 112 h | 176 h | équilibré avec les collaborateurs comparables |
| Adam | 1.0 | 88 h | 112 h | 176 h | équilibré avec les collaborateurs comparables |
| Florian | 1.0 | 80 h | 112 h | 176 h | équilibré avec les collaborateurs comparables |
| Kristina | 1.0 | 80 h | 112 h | 176 h | équilibré avec les collaborateurs comparables |
| Michael | 1.0 | 128 h | 112 h | 176 h | équilibré avec les collaborateurs comparables |
| Mila | 1.25 | 176 h | 112 h | 176 h | équilibré avec les collaborateurs comparables |
| Sabrina | 1.0 | 88 h | 112 h | 176 h | équilibré avec les collaborateurs comparables |
| Sahra | 1.25 | 176 h | 112 h | 176 h | équilibré avec les collaborateurs comparables |
| Simona D. | 1.0 | 80 h | 112 h | 176 h | équilibré avec les collaborateurs comparables |
| Zaki | 1.0 | 80 h | 112 h | 176 h | équilibré avec les collaborateurs comparables |


### Compléments du 19/11 (soir) : cas des 56 h, volume de février, vérifications

**Cas des 56 h** : le message ne nommait ni le mois ni les collaborateurs. Trois plannings enregistrés présentent exactement ce profil (une personne vers 56 h, d'autres à 168–192 h) : compte d'essai février 2027 (version 1 du 19/11 à 12:05, planning actif : Chloé 56 h ; Abdu, Mila, Sahra 176 h), compte d'essai novembre 2026 (version 1 du 17/11 : Aziza 56 h ; trois à 176 h), démonstration novembre 2026 (archive du 19/11 à 15:27 : Valérie 56 h ; trois à 168–192 h). Rejoués sur la copie avec leurs paramètres d'origine par le moteur PRÉCÉDENT (code exact du commit b423618) : février reproduit à l'identique (Chloé 56 h ; Abdu, Mila, Sahra 176 h), les deux novembre reproduits (trois collaborateurs à 176 h). Moteur corrigé :
- février : groupe Ploom prioritaire 80–176 h → 112 h pour tous ; **Chloé 56 → 40 h** : elle ne peut travailler que 12 jours (prioritaire seulement sur Valmont, Cartier en renfort) et ses heures possibles au-delà sont des shifts optionnels Valmont sans budget (voir ci-dessous) ; elle reçoit la même proportion de ses jours possibles que les autres. Son cas n'est donc corrigé que pour la cause « priorité automatique » ; augmenter ses heures relève du volume optionnel, à décider ;
- novembre (essai) : Aziza 56 → 88 h, groupe Ploom 104–176 → 120–128 h ; novembre (démonstration) : Valérie 56 → 104 h, groupe Ploom 96–192 → 136–144 h ;
- dans les trois cas : 0 violation de règle obligatoire (vérificateur indépendant), couverture obligatoire inchangée (100 %), niveaux prouvés optimaux en 9 à 12 s.

**Février 2027 sans budget : 12 shifts optionnels de moins (−96 h)**. Besoins saisis : 156 obligatoires (Ploom, Cartier : 1 248 h) et 104 optionnels (Cailler 24, Cellcosmet + Nuxe 20, Valmont 60 : 832 h) ; aucun budget du mois (seul un budget de base Nuxe de 88 h existe, non appliqué : planning antérieur au préremplissage). Les optionnels n'ont donc aucun objectif de volume : l'ancien moteur en retenait 42 (336 h) parce que ses cibles tiraient les heures vers le haut ; le moteur corrigé en retient 30 (240 h) : Cailler 144 → 88 h, Cellcosmet + Nuxe 64 → 48 h, Valmont 128 → 104 h ; 26 shifts ont quitté le planning et 14 y sont entrés. Obligatoires : 156/156 avant et après.

**Ajouts** : après chaque génération, le volume attribué est présenté à part de l'équité (obligatoires, optionnels, heures, et planning remplacé) ; toute baisse des optionnels est signalée et expliquée (marques sans budget). Le planning liste les **besoins optionnels non attribués** par marque (shifts, heures, budget ou « aucun budget ») avec « Placer et attribuer » (shift créé sans collaborateur, puis fenêtre d'attribution habituelle). Le résultat distingue « meilleure solution prouvée » et « planning valide, optimisation non terminée » (règles obligatoires vérifiées, durée maximale atteinte, planning utilisable).

**Vérifications complétées sur la pile isolée** : second onglet sans temps réel → enregistrement arrêté au premier envoi refusé, aucun envoi ensuite, pas de « Réessayer » ; second onglet avec temps réel → brouillon supprimé signalé sans action ; recalcul d'une nouvelle marque → besoins manquants listés avec le lien vers « Sites et marques », lancement impossible, budget saisi dans la fenêtre puis « prête pour le calcul » ; annulation pendant le calcul (moteur démarré) → planning initial et versions inchangés.

**Deux défauts réels trouvés par ces vérifications, corrigés**
- **Annulation pendant le calcul** : la solution trouvée avant l'annulation était enregistrée (calcul « annulé », planning pourtant remplacé). Désormais jamais enregistrée ; raison « Calcul annulé ». Test API de non-régression (échoue sans la correction).
- **Calcul terminé après la suppression du planning** : il avait écrit 196 affectations, 196 shifts et une version dans le planning supprimé (pile isolée ; vérifié : rien de tel dans la base réelle). Désormais : planning verrouillé à l'enregistrement, rien n'est écrit (raison « planning supprimé pendant le calcul ») ; la suppression annule les calculs en file ou en cours ; et la base refuse toute écriture de shift ou d'affectation dans un planning supprimé (migration 0020). Test API.

**Incident non expliqué (ouvert)** : `e2e/integration.spec.ts`, préparation du mois (19/11 vers 21:35) : l'attente « affectations > 0 » a échoué avec « 50 s dépassées » alors que le journal montre 7 lectures puis le nettoyage de fin de test 5 s après la création du mois, avant la fin du calcul (qui a ensuite écrit dans le planning supprimé : défaut ci-dessus, corrigé). Pourquoi l'attente s'est arrêtée au bout d'environ 5 s n'est pas établi ; relancé ensuite, le même test a passé sa préparation. Aucun délai modifié.

**Dépendance de test corrigée (cause confirmée)** : `test_replacement_offers::test_acceptation_validee_puis_double_clic` a échoué une fois dans la suite complète ; il supposait un ordre fixe entre « lancée » et « envoyée », deux événements écrits dans la même transaction (même horodatage, ordre défini par un identifiant aléatoire). Le test vérifie désormais l'ordre réel (acceptation après) et la simultanéité des deux autres ; suite API complète ensuite : 191 / 191.

**Cas Chloé (février 2027, compte d'essai) : 56 h → 40 h, analyse complète sur la copie**
- Disponibilités réelles : indisponible tous les mercredis et samedis (fiche) ; aucune absence, aucun congé, aucun contrat, aucune limite de jours.
- Habilitations : Valmont (prioritaire) et Cartier (renfort) uniquement ; aucune autre marque autorisée. Préférence horaire souple 10:00–19:00. Aucune exclusivité configurée (la notion n'existe pas dans l'application) : être prioritaire sur Valmont n'interdit rien ; Cartier lui reste ouvert, en renfort.
- Besoins et budgets : Valmont 60 shifts optionnels (lundi, mercredi, jeudi, vendredi, samedi), Cartier 8 shifts obligatoires (vendredis et samedis) ; aucun budget du mois.
- Jours où elle peut réellement travailler : 12 (lundis, jeudis, vendredis) ; aucun besoin de ses marques les mardis et dimanches ; mercredis et samedis indisponibles. **Maximum réellement atteignable : 96 h** (12 jours × 8 h).
- Transferts vérifiés un à un par le vérificateur indépendant (sur le planning du moteur corrigé, couverture inchangée) : 5 possibles sans aucune nouvelle violation — 3 shifts Valmont tenus par Ying (08:00–17:00, hors de sa préférence) et 2 shifts Cartier tenus par Zaki (renfort pour elle). Chaîne de ces 5 transferts : Chloé 40 → 80 h ; puis 2 besoins Valmont optionnels réels non attribués, sur ses derniers jours libres : 96 h. Aucun blocage dur.
- Pourquoi le moteur ne les fait pas, et pourquoi ce n'est pas une erreur d'équité : à jours possibles comparables, sa charge est déjà au niveau de ses pairs (heures / référence : Chloé 0,42 ; Ying 0,40 ; Jane 0,38 ; Aziza 0,42 ; Valérie 0,42 — tous sur des marques aux besoins optionnels sans budget) ; le groupe Ploom est à 0,50 parce que ses besoins sont obligatoires. Prendre les shifts Valmont de Ying ferait passer Ying à 0,25 ; prendre les shifts Cartier de Zaki utiliserait son niveau renfort (dernier recours) sans relever le minimum de l'équipe. Simulations sur la copie : Cartier en « secondaire », sa préférence horaire retirée, ou les deux — résultat identique (Chloé 40 h). **Pas de correction du moteur** : aucune répartition à la fois plus équitable et conforme à la configuration n'existe ici.
- Leviers qui relèveraient ses heures (décisions de l'utilisateur, aucune appliquée) : un budget Valmont pour le mois (volume visé pour ses besoins optionnels), les compléments manuels depuis « Besoins optionnels non attribués », ou un ajustement manuel après génération (mérite, priorité) ; le planning affiche les shifts concernés.

**Données** : les tableaux de ce document nomment désormais les collaborateurs par prénom et initiale. Le commit 33d3c7d (déjà poussé) contenait les noms complets : ils restent dans l'historique de la branche tant qu'une réécriture n'est pas décidée.

## Lenteurs et échecs intermittents : analyse du 19/11/2026

Diagnostics ajoutés et conservés : en-tête `Server-Timing` sur chaque réponse (durée de traitement côté serveur), journal des requêtes au-delà de 500 ms (méthode, modèle de route, durée ; aucune donnée), trace Playwright conservée uniquement en cas d'échec (réseau, durées, état de la page).

**Causes démontrées et corrigées**
- **Double rechargement après chaque modification** (démontré dans le journal du serveur) : l'écran se rechargeait lui-même, puis l'annonce temps réel de SA propre modification le rechargeait une seconde fois ; le planning relisait en plus planning et rappels en double. Chaque modification déclenchait donc deux salves d'une quinzaine de lectures lourdes (conflits, compatibilité, dimanches, calendrier, suivi…). Corrigé : l'onglet joint un identifiant à ses modifications ; il ignore sa propre annonce s'il vient de se recharger (les autres onglets et managers sont toujours prévenus) ; une seule salve par modification (vérifié dans le journal : chaque lecture lourde une fois au lieu de deux).
- **Historique** : chaque lecture chargeait TOUTES les versions de l'entreprise avec leur contenu complet (instantanés) pour connaître leur planning, et toutes les générations. Désormais seulement les identifiants utiles des événements lus. Mesure sur la pile isolée, mêmes données (9 166 entrées du journal, 117 versions) : 340–630 ms → 73–155 ms.
- **Impact d'une fiche sur les plannings** : deux rapports de compatibilité complets par mois (avec leurs compléments d'affichage), chacun relisant toutes les données de référence de l'entreprise. Désormais : calcul allégé (mêmes incompatibilités) et données de référence lues une fois par requête (cache limité à cette lecture, vidé à toute écriture). Résultat identique (test d'équivalence avec le rapport complet) ; médianes entrelacées sur 3 mois générés : 386 → 241 ms (−38 %). Le coût reste proportionnel au nombre de mois ayant un planning.

**Mécanisme mesuré d'échecs intermittents (suites en parallèle)** : sous charge extrême (suites API et navigateur simultanées, charge moyenne jusqu'à 16), le journal relève, côté serveur : impact d'une fiche jusqu'à 5,9 s, attribution manuelle jusqu'à 4,5 s, compatibilité, calendrier et dimanches jusqu'à 2,9 s. Les tests attendent l'écran 5 s : un dépassement est donc possible dans ces conditions. Cela explique de façon plausible et mesurée les échecs `team` (impact d'une fiche), `wfm` (versions), `reassign` (glisser-déposer) et `integration` (attribution) observés en parallèle ; ces occurrences passées n'avaient toutefois pas été instrumentées : le lien reste **probable, non démontré** pour chacune. Les délais des tests n'ont pas été allongés. Après corrections, une exécution dans ces mêmes conditions : navigateur 85 / 85, API 177 / 177 — une exécution réussie ne vaut pas preuve de résolution.

**Reste ouvert (non corrigé)**
- Une API = un processus Python : les lectures lourdes simultanées se ralentissent mutuellement (conflits : ≈ 30 ms seule, ≈ 500 ms dans une salve, jusqu'à 2,9 s sous charge). Chaque lecture reconstruit les données du mois (≈ 25 requêtes) ; piste : mutualiser ce calcul par révision des données, ou plusieurs processus. À traiter avec la mise en production (D1).
- `test_monthly_setup::test_10` (18/11), `test_demo_flow::test_manual_move…` (18/11), `test_history…` (19/11), `wizard` janvier 2027 : causes non confirmées (détail ci-dessous), aucune nouvelle occurrence depuis ; les diagnostics ajoutés permettront de trancher à la prochaine.

## Stabilité des tests (18/11/2026)

Moteur : **136 / 136** tests de correction le 18/11 (code du moteur inchangé depuis `b9fed88` ; l'équité sur plusieurs mois est couverte et passe) ; mesure de performance sur `b9fed88`, machine au repos : 46 s pour un budget de 45 s (`docs/mesures-moteur.md`).

Cinq exécutions complètes de la suite API, dont quatre en parallèle de la suite navigateur (les conditions de l'échec initial) :

| Exécution | Conditions | API | Navigateur (en parallèle) |
|---|---|---|---|
| 1 | en parallèle | 161 / 161 * | 70 / 71 : `wizard` (janvier 2027) |
| 2 | seule | 161 / 161 * | — |
| 3 | en parallèle | 160 / 161 : `test_monthly_setup::test_10` | 74 / 74 |
| 4 | en parallèle | 161 / 161 * | 74 / 74 |
| 5 | en parallèle | 161 / 161 * | 74 / 74 |

\* 160 tests + une sonde temporaire, retirée ensuite.

**Incertitudes restantes (causes non confirmées)**
- Suites lancées EN PARALLÈLE (API + navigateur sur le même Mac, conditions volontairement extrêmes), 19/11 : deux exécutions. La première : API 170 / 170, navigateur 78 / 80 (`budget-base`, puis `wfm` versions). La seconde : API 170 / 170, navigateur 72 / 75 (`reassign` glisser-déposer, `team` impact d'une fiche, `wfm` versions).
  - `budget-base` : cause **confirmée**, un budget d'octobre 2027 laissé par l'exécution précédente (le budget du mois survit, à juste titre, à la suppression d'un planning). Le test vérifie maintenant sa précondition et nettoie le budget du mois ; deux exécutions successives réussies.
  - Les autres attendent un résultat d'écran qui dépend d'une réponse du serveur (5 s). Temps mesurés pendant la suite API, aux mêmes actions : jusqu'à 2,9 s, contre 0,3 s au repos (charge moyenne jusqu'à 19,8). Le ralentissement est réel ; le dépassement de 5 s, lui, n'a pas été mesuré directement. Cause **probable**, non confirmée ; les délais n'ont pas été allongés.
  - Amélioration d'écran retenue : une copie de travail supprimée disparaît aussitôt de la liste des versions, sans attendre le rechargement complet.
  - Navigateur seul (conditions normales), après corrections : 82 / 82.
- `e2e/integration.spec.ts`, attribution depuis le suivi de couverture (19/11) : un échec au premier passage, juste après la reconstruction des images Docker (charge moyenne d'environ 13). Le journal du serveur montre que la réponse à l'attribution (`manual-assign`, 200) est arrivée après le délai d'affichage de 5 s : même la modification faite au nettoyage du test avait déjà obtenu sa réponse. Hypothèse « premier chargement des modules après redémarrage » testée en redémarrant seulement l'API : **non confirmée** (938 ms). Quatre passages suivants réussis, de 923 à 1 177 ms. Cause **probable**, non démontrée : la charge de la machine. Le test enregistre désormais la durée réelle de l'attribution ; aucun délai n'a été allongé. Correction (19/11, mesure détaillée) : la « durée ≈ 1 s » mesurée par le test incluait l'attente du clic (animation d'ouverture de la fenêtre) ; la requête part sans attente et le serveur répond en 230 à 300 ms (en-tête Server-Timing). Ce n'était pas une lenteur du serveur.
- Dépendance entre les deux scénarios de `e2e/integration.spec.ts` (19/11), cause **confirmée** en base : le premier laissait dans novembre 2027 une affectation verrouillée, attribuée à un collaborateur supprimé ensuite, sur une marque archivée. Le recalcul du second scénario était donc, à juste titre, infaisable (planning initial conservé). Corrigé : un mois dédié par scénario (novembre et décembre 2027), et le résultat affiché porte un repère explicite (remplacé ou conservé) au lieu d'une recherche de texte.
- `test_history::test_generation_remplacement…` (19/11) : un échec dans la suite complète, jamais seul. Défaut réel identifié dans le test : il comparait strictement l'heure de la base (début de transaction) à l'horloge de la machine de test, alors qu'un écart d'environ 1 ms (base en retard) a été mesuré. Tolérance explicite d'une seconde dans les deux sens (jamais avant l'envoi, jamais après la réponse) et message détaillé ; l'ordre des événements et leurs heures (même horloge, celle de la base) restent vérifiés strictement. Suite API complète après correction, en parallèle des tests navigateur : 167 / 167 (navigateur 79 / 79). Le détail de l'échec initial n'avait pas été capturé : cause **probable**, non confirmée, et une suite réussie ne suffit pas à établir la résolution.
- `test_demo_flow::test_manual_move_reports_conflicts_immediately` : un échec, le 18/11, dans une suite complète en parallèle des tests navigateur ; jamais reproduit depuis (5 suites complètes, 11 exécutions isolées dont 6 sous forte charge). Cause **probable, non confirmée** : l'ancienne version prenait le premier shift GVA9 et cherchait un seul collègue ce jour-là ; une sonde a montré qu'il ne restait parfois qu'**un** collègue possible (1 fois sur 6 observations), ce qui rend plausible un cas sans candidat selon la solution du moteur. La version actuelle cherche parmi tous les couples possibles (88 à 112 selon les exécutions) ; elle a passé toutes les exécutions depuis. Le mode d'échec exact de l'occurrence initiale n'a pas été enregistré.
- `test_monthly_setup::test_10` : échec 1 fois sur 5 (exécution 3), même symptôme que le 17/11 (décembre régénéré sans remplacer le planning). La cause du 17/11 (verrou posé par un test précédent, « affectation verrouillée impossible ») est corrigée ; la cause de l'échec du 18/11 n'est **pas confirmée** : une sonde ajoutée ensuite a donné « faisable » ou « optimal » dans les exécutions 4 et 5. Hypothèses : calcul « interrompu » faute de temps sous forte charge (délai de 20 s), ou autre refus. Le test affiche désormais, s'il échoue, le résultat du calcul et ses diagnostics, pour trancher à la prochaine occurrence.
- `e2e/wizard.spec.ts` (janvier 2027) : échec 1 fois sur 4 en parallèle de la suite API, jamais seul. Cause **probable, non confirmée** : l'attente de l'enregistrement automatique de l'effectif (5 s) dépassée sous charge ; l'effectif enregistré ne contenait ensuite aucune ligne bloquée. Le délai n'a pas été allongé.

## Régénération, enregistrement automatique et temps de calcul (18/11/2026)

**Régénération qui laisse l'ancien planning en place**
- Inventaire du code : l'ancien planning est conservé dans cinq cas seulement. (1) Calcul infaisable, par exemple un shift verrouillé devenu impossible : cause **confirmée** de l'échec du 17/11, corrigée côté test. (2) Calcul interrompu sans aucune solution. (3) Refus par le vérificateur avant l'enregistrement. (4) Refus à la relecture du planning enregistré, l'enregistrement étant alors annulé. (5) Annulation.
- Aucun chemin où un calcul réussi garderait des affectations de l'ancien planning, hors verrous. Un verrou sur un shift qui n'existe plus rend le calcul infaisable (vérifié dans le moteur et par un test).
- Chaque calcul enregistre désormais un **résultat d'enregistrement** : planning remplacé ou conservé, code et texte de la raison, affectations et version avant / après, verrous conservés. Il enregistre aussi les **temps mesurés** de chaque étape. Les écrans « Générer » et l'assistant affichent ce résultat (« Le planning précédent est conservé — Pourquoi : … »), vérifié dans le navigateur sur un cas réel. Les messages de verrou n'affichent plus d'identifiant interne.
- L'échec de `test_10` du 18/11 (1 suite sur 5) reste **non expliqué** : il est survenu avant cette instrumentation. Il ne s'est pas reproduit dans les deux suites complètes lancées ensuite en parallèle des tests navigateur (API 161 / 161 les deux fois, navigateur 74 / 74 puis 75 / 75). Cette absence ne prouve pas qu'il soit résolu. S'il se reproduit, le message du test affichera le résultat d'enregistrement et les diagnostics.

**Enregistrement automatique de l'effectif (assistant)**
- Vrais défauts trouvés dans l'écran, indépendants du test. « Enregistré automatiquement » s'affichait à la fin d'un premier envoi alors que d'autres modifications partaient encore. Deux envois pouvaient être simultanés, et une réponse ancienne pouvait écraser l'affichage. Aucun « Réessayer » en cas d'échec. Enfin, l'état « Enregistré » restait affiché d'une action à l'autre, et c'est ce qui trompait le test.
- Corrections : file d'enregistrement (un envoi à la fois, « Enregistré » seulement après confirmation de toutes les modifications, erreur affichée avec « Réessayer » et modifications conservées), testée seule (3 tests unitaires) et dans le navigateur (échec simulé puis reprise confirmée par le serveur).
- Le test attend une confirmation réelle (compteur de confirmations du serveur), avec une limite de 15 s, au lieu de l'ancienne attente de 5 s.

**Temps de calcul** : décomposition mesurée dans `docs/mesures-moteur.md`. Les 46 s pour 45 s correspondent à 0,4 s de dépassement du solveur et 0,65 s de contrôles du moteur. Le libellé de la durée maximale indique désormais ce qu'elle borne (construction du modèle et recherche) et ce qui s'y ajoute.

## Vérifications ciblées

| Exigence | Preuves exécutées |
|---|---|
| **Plafond de 176 h** (travail effectif, tous sites et marques, mois civil) | Moteur : plafond strict (sans plafond, 26 shifts soit 208 h ; avec, 22 shifts soit 176 h). Heures d'une période voisine du même mois comptées. Shift de nuit rattaché au mois de son début. Dépassement fixé conservé, jamais aggravé. API : génération ; ajout, transfert, réaffectation, changement d'horaire et restauration refusés au-delà ; réduction d'un dépassement permise ; réoptimisation locale d'un planning qui dépasse déjà. E2E : transferts refusés avec la règle affichée (« … travaillerait 184 h »). |
| **Minimum et maximum de jours par mois** (indépendants, « Pas de préférence », une journée comptée une fois) | Moteur : maximum strict avec deux shifts le même jour ; minimum obligatoire ; minimum impossible bloqué avec la raison (jours possibles, plafond, jours consécutifs, minimums incompatibles entre eux). API : incohérences refusées (minimum supérieur au maximum, minimum incompatible avec le plafond) ; exception du mois sans effet sur les autres mois ; blocage signalé avant génération. Unitaires et e2e : formulaires. |
| **Indépendance des plannings et paramètres conservés** | API : une fiche modifiée ne crée aucune incompatibilité dans un planning existant. Générer un autre mois ne touche pas le premier. « Appliquer les paramètres actuels » est explicite et ne déplace aucune affectation. Pondérations de la génération conservées. Collaborateur ajouté ou supprimé après coup : aucun effet rétroactif. E2E : fiche modifiée, novembre inchangé, détail « si appliqués ». Démo : novembre identique à la sauvegarde du 17/11 à 8 h 22. |
| **Vérificateur indépendant** (Python, sans CP-SAT) | Exécuté après le calcul, sur les données relues et sur le planning enregistré. Plan rejeté si une contrainte est violée (test de solveur volontairement faussé). Donnée modifiée pendant le calcul : plan rejeté. Également après un ajout, un transfert, une restauration ou une simulation appliquée. |
| **Planning mensuel individuel** | API : lecture seule (aucune période créée, aucune donnée modifiée), compteurs exacts (travail effectif, jours, dimanches, présence, pauses), congés et indisponibilités distingués. E2E : ouverture depuis la liste (mois en cours) et depuis le planning général (mois consulté), décembre → janvier, mois sans planning (« Aucun planning pour … »), « Aujourd'hui », compteurs comparés au planning, filtres conservés au retour, réaffectation par la même confirmation que le planning général. |
| **Rappel « À régulariser »** (double affectation confirmée) | API : enregistrement provisoire, rappel unique (pas de doublon), chevauchement toujours en conflit, validation refusée tant qu'il subsiste, rappel supprimé automatiquement après retrait ou réattribution de l'affectation initiale, besoin initial dans la couverture non assurée. E2E : rappel affiché, conservé après actualisation, « Voir le shift initial », « Retirer l'affectation » avec confirmation, disparition. |
| **Explication des incompatibilités** | Moteur : chaque incompatibilité indique le collaborateur, la date, les horaires, le site, la marque, la règle, la limite et la valeur atteinte, la raison, et sa nature (obligatoire ou préférence). E2E : bandeau « N incompatibilités », puis « Voir le détail » liste chaque problème. |

---

## A. Terminé et vérifié

**Données et exploitation**
- Restauration réelle des sauvegardes dans une base isolée (`scripts/ops/verify_backup.sh`).
- Sauvegarde vérifiée à la création (`scripts/ops/backup.sh`).
- Alerte stockage (`scripts/ops/check_storage.sh`).
- Tests sur des bases distinctes de la base de développement : API sur base jetable, e2e sur pile isolée.
- Nettoyage de 788 tenants de test identifiés avec certitude. Après sauvegarde vérifiée, aucune référence croisée ; les tenants conservés sont identiques avant et après.

**Moteur**
- CP-SAT conservé, sur la base de mesures (`docs/moteur-evaluation.md`).
- Contraintes obligatoires jamais compensées par un meilleur score.
- Ordre de priorité explicite : couverture, puis engagements, puis optimisation.
- Verrous respectés ; réoptimisation complète, partielle et locale ; stabilité.
- Calcul en arrière-plan avec état, temps écoulé et annulation.
- Statuts distincts : optimal prouvé, faisable, partiel, impossible prouvé, délai sans solution, erreur.

**Règles**
- Plafond de 176 h, présenté comme règle interne et non légale.
- Minimum et maximum de jours par mois, objectifs et limites contractuels.
- Disponibilités récurrentes et datées, congés.
- Horaires autorisés par site et marque, préférence horaire souple ou stricte.
- Sites, marques, missions, compétences avec dates d'expiration.
- Repos quotidien, repos hebdomadaire et jours consécutifs, y compris à la frontière entre deux mois.
- Pauses du référentiel, besoins par créneau et compétence, budgets d'heures et de coûts.
- Référentiel réglementaire daté, versionné et à valider.

**Historique**
- Affectations préservées ; dépassements historiques signalés sans être comptés comme incompatibilités.
- Aggravation interdite, réduction permise.
- Paramètres historiques jamais modifiés silencieusement.

**Temps**
- Minutes entières ; présence, pause et travail effectif distincts.
- Passage de minuit, changements d'heure, chevauchements entre sites.
- Un jour compté une seule fois ; frontière entre deux mois.
- Co-branding sans double comptage.

**Indépendance**
- Paramètres conservés par planning : fiches, effectif, règles, pondérations, plafond, calcul d'origine.
- Vérificateur indépendant du générateur. Pause exigée, horaires par boutique et catégorie horaire sont réécrits dans le vérificateur, avec un test d'équivalence sur 2 000 cas. Seul le calcul horaire de base (`timecalc`), qui est la référence commune, reste partagé.
- Absence sur un planning validé ou publié : notification « Révision proposée » aux gestionnaires (shifts concernés, sans doublon), bandeau dédié, aucune modification automatique (test API).
- Exports PDF et Excel dans l'identité rose et blanc : en-têtes roses, lignes alternées, volets figés, filtres (test API).
- Contexte de génération figé et immuable dans chaque version ; conformité aux règles de création et aux règles actuelles (datée, informative).
- Action explicite avec aperçu ; choix obligatoire des paramètres lors d'une régénération quand ils ont changé.
- Mois voisin lu sans être modifié.
- Statuts et versions restaurables, comparaison des versions, journal d'audit.

**Diagnostics**
- Incompatibilités détaillées, avec la marque.
- Noyau d'infaisabilité et verrous impossibles.
- Raison de l'inadmissibilité d'un collaborateur.
- Contrôles avant génération : minimums impossibles, créneaux obligatoires sans collaborateur admissible, capacité inférieure aux besoins, budget strict inférieur aux besoins.

**Collaborateurs**
- Fiche complète (nom et prénom séparés) et contrôle des doublons.
- Messages exacts d'ajout et de suppression.
- Suppression qui conserve l'historique, avec réintégration ; affectations à venir indiquées avant confirmation.
- Données personnelles réservées aux rôles qui gèrent les fiches.
- Fiches complétées à partir de la liste fournie, sans fusion des cas ambigus ; deux identités incertaines laissées à compléter, sans déduction.

**Identité visuelle**
- Rose exact de l'image (Display P3, repli sRGB #CC0256) et blanc glassmorphism, par défaut sur tous les écrans.
- Mode sombre facultatif, sur choix explicite.
- Contrastes vérifiés ; 19 écrans contrôlés sur ordinateur et sur mobile : thème clair, aucun débordement horizontal, aucun fond sombre, aucune erreur JavaScript.

**Parcours**
- Vues mois, planning général, **semaine** (du lundi au dimanche, shifts regroupés par site, nombre exact vérifié jour par jour), jour, collaborateur, marque/site.
- Filtre **client** dans toutes les vues du planning (shifts dont une marque appartient au client, co-branding compris).
- Recherche, filtres, annuler et rétablir, compteurs.
- Exports PDF, Excel, CSV et ICS.

**Planning individuel et régularisations**
- Planning mensuel de chaque collaborateur, ouvert depuis son nom (liste des collaborateurs ou planning général) : calendrier, horaires, pauses, sites, marques, congés et indisponibilités, totaux du mois et plafond applicable ; navigation entre les mois et les années ; rien n'est créé en consultant.
- Rappels « À régulariser » persistants (table `regularizations`, migration 0012) après une double affectation confirmée ; rien n'est retiré ni réattribué automatiquement.

**Règles et opérations de planning** (moteur, vérificateur indépendant, contrôle des modifications manuelles, écrans ; migration 0013)
- Relations « à séparer » : portées « même jour, même site », « même jour, tous sites » et « horaires qui se chevauchent », strictes ou souples (coût identique entre le solveur et l'évaluateur indépendant).
- Absences sur une partie de la journée : seuls les shifts qui chevauchent le créneau sont impossibles ; affichées dans le planning individuel.
- Horaires obligatoires par collaborateur (contrainte stricte).
- Temps de déplacement entre sites (écart exigé = le plus grand du repos quotidien et du déplacement).
- Pauses sans relève sur les sites à présence continue : alerte de couverture (jamais un blocage).
- Modification groupée (planning individuel, « Transférer plusieurs shifts… ») : plusieurs shifts changent de titulaire en une opération, tout ou rien ; chaque transfert est contrôlé sur le planning où les autres sont déjà appliqués (alertes datées au bon jour, effets combinés compris), une seule confirmation, plafond jamais dérogeable.
- Échange réciproque de deux shifts et duplication d'un shift sur d'autres jours : même contrôle et même confirmation qu'une affectation manuelle, tout ou rien, dérogations tracées, plafond mensuel jamais dérogeable.
- Indépendance des plannings : horaires obligatoires et temps de déplacement sont conservés par chaque planning ; un planning antérieur à ces règles n'en hérite pas (différence seulement signalée, « Appliquer les paramètres actuels » reste explicite).

**Équité sur plusieurs mois**
- Le moteur reçoit, pour chaque collaborateur, les jours de week-end et les dimanches travaillés dans les 3 mois civils précédents. Un shift de week-end ou de dimanche coûte davantage à qui en a eu plus que la moyenne de l'équipe ; à heures égales, les week-ends vont d'abord à ceux qui en ont eu le moins (test : la décision suit l'historique dans les deux sens). Coût identique entre le solveur et l'évaluateur indépendant.
- Rapport d'équité sur plusieurs mois disponible par l'API (`/reports/fairness`) ; la page « Équité » a été retirée de l'interface à votre demande.
- Plannings existants : ce nouveau critère ne s'applique pas à une régénération avec les paramètres conservés et n'apparaît pas comme une « différence ».

**Espace collaborateur et circuit d'approbation** (migration 0014)
- Depuis « Mon planning », un collaborateur relié à sa fiche demande un congé, une absence (journée ou partie de journée), un changement de ses indisponibilités hebdomadaires (appliqué aux prochains plannings ; les plannings existants gardent leurs paramètres) ou un échange de shifts avec un collègue ; il suit le statut et peut annuler tant que rien n'est décidé.
- Échange : accord du collègue d'abord, puis décision du responsable ; l'approbation passe par le même contrôle qu'un échange fait à l'écran (alertes, dérogation réservée, plafond jamais dérogeable). Échange devenu impossible (planning modifié) : signalé, jamais appliqué.
- Page « Demandes » des responsables : shifts concernés affichés avant la décision ; un congé ou une absence approuvés ne retirent aucun shift (révision proposée si le planning est officiel). Un responsable ne traite jamais une demande qui le concerne.
- Notifications à chaque étape ; demandes incluses dans l'export et l'effacement RGPD.

**Historique des modifications** (journal d'audit existant, complété ; aucune copie)
- Page « Historique », fenêtre « Historique » du planning (mois affiché) et section de la fiche collaborateur.
- Chaque événement, en langage simple : date et heure de la modification (fuseau de l'entreprise), auteur, planning, date du shift (distincte), collaborateurs, site, marque, ancienne et nouvelle valeur.
- Types : ajouts, suppressions, remplacements, échanges, changements d'horaires, modifications groupées (résumé et détail consultable), verrouillages, générations, propositions appliquées, restaurations et publications de versions.
- Filtres : période, collaborateur, site, marque, utilisateur, type d'action ; « Afficher plus » pour remonter le temps.
- Droits : planning complet pour les rôles qui le lisent ; un responsable de marque ne voit que ses marques ; un collaborateur n'y a pas accès.
- Seules les opérations réussies apparaissent (journal écrit dans la même transaction) ; les noms sont figés au moment de la modification (collaborateur retiré toujours lisible) ; les informations absentes des anciens événements sont indiquées « non enregistré », jamais déduites.
- Aucune opération ne change le site ou la marque d'un shift existant : ces informations figurent dans chaque événement, mais il n'y a pas d'événement « changement de site ou de marque » à enregistrer.

**Interface simplifiée** (le moteur est inchangé)
- Retirés de l'interface : « Rentabilité », « Équité », « Simulations », ainsi que leurs cartes (équité et coût/marge du tableau de bord) et raccourcis. Les mécanismes internes restent : optimisation, équilibrage (y compris sur plusieurs mois), contraintes, pondérations, contrôles, aperçus de réoptimisation dans « Déclarer une absence » et pour les missions. Aucune donnée ni règle supprimée.
- Navigation : Planning (tableau de bord, planning, génération, alertes, historique, versions), Équipe (collaborateurs, demandes, heures réelles), Configuration (sites et marques, clients, budgets, règles, paramètres, import / export).
- Paramètres : les priorités courantes restent visibles ; la logique d'optimisation, les poids bruts du moteur et l'influence de la dernière génération sont rangés dans « Paramètres avancés ». Aucune valeur n'a été modifiée (vérifié par un test).

**Suppression d'un planning généré** (migration 0015)
- Action « Supprimer ce planning » dans les options du planning, réservée au droit « planning.delete » (propriétaire et administrateur), vérifié côté serveur, entreprise garantie par la RLS.
- Fenêtre « Supprimer le planning de [mois année] ? » : mois et année, affectations (dont verrouillées), shifts, versions associées (dont publiées, que les collaborateurs ne verront plus), rappels ; suppression refusée si des heures réelles sont rattachées (archivage possible).
- Confirmation par le mot de passe du compte connecté, vérifié par le serveur, jamais stocké ni journalisé ; 5 échecs par quart d'heure et par compte au plus (compteur Redis) ; pas de double soumission (bouton désactivé, verrou du planning, « déjà supprimé »). L'application n'a pas de connexion externe aujourd'hui (mot de passe local obligatoire) ; un compte sans mot de passe local recevrait « réauthentification requise ».
- Suppression logique en une transaction : archive des affectations conservée avec le planning, affectations et shifts retirés des vues actives, versions et calculs conservés mais ni consultables ni restaurables, entrée « Suppression d'un planning » au journal (planning, date et heure, nom et identifiant interne de l'auteur, nombre d'affectations). Rien d'autre modifié ; aucun planning recréé ; un nouveau planning du même mois peut être créé explicitement.
- Après suppression, un nouveau planning du même mois se crée explicitement et se génère normalement : nouvel identifiant, rien de l'ancien repris, numérotation des versions propre, ancien planning jamais réactivé (archive inchangée) ; dans l'historique, l'ancien apparaît « (planning supprimé le …) », séparé du nouveau (tests API et navigateur).
- **Depuis le menu latéral** « Historique des plannings » : bouton « ⋯ » sur chaque mois (ordinateur et mobile) → « Supprimer ce planning », brouillon jamais généré compris, sans ouvrir le planning. Même fenêtre (mois, année, statut), même mot de passe, même suppression logique, même trace (y compris 0 affectation). Le mois disparaît aussitôt du menu ; s'il était consulté, redirection vers le mois disponible le plus proche (ou la création d'un planning). Un ancien onglet qui enregistre encore est refusé par le serveur et son enregistrement automatique s'arrête (« Enregistrement arrêté ») ; rien n'est recréé. L'ancienne suppression définitive d'un brouillon, sans mot de passe ni trace, est retirée (410).
- Trace protégée en base : le planning supprimé et l'entrée du journal ne peuvent être ni modifiés ni effacés (déclencheurs), sauf effacement RGPD explicite (qui anonymise aussi l'archive) ou purge de tenants de test.
- Tests : annulation, mauvais mot de passe, tentatives répétées, accès non autorisé, autre entreprise, compte externe simulé, heures réelles, suppression réussie, autres mois intacts, historique persistant, protection en base (API et navigateur).
- **Récupération contrôlée** (préparée, non exécutée sur un mois réel) : depuis l'événement « Suppression d'un planning » de l'historique, « Préparer une récupération » (même droit, même mot de passe, mêmes limites de tentatives). Aperçu sans effet (essai à blanc annulé) : affectations archivées, verrouillées, replaçables, collaborateurs introuvables (jamais remplacés par d'autres). La confirmation crée un NOUVEAU planning du mois à partir de l'archive (mêmes jours, horaires, sites, collaborateurs, verrous, effectif et paramètres conservés du mois) ; refusée si le mois a déjà un planning actif ; plafond mensuel appliqué (tout ou rien) ; rien n'est publié. Le planning supprimé, son archive et la trace de suppression restent inchangés ; aucun autre mois lu ni modifié ; entrée « Récupération d'un planning supprimé » au journal (API et navigateur).
- Tenant de démonstration, suppressions du 19/11 (essais de l'utilisateur, compte propriétaire, confirmé par lui) : avril 2027 (12:16, 237 affectations archivées), février, janvier 2027, décembre et novembre 2026 (15:27, archives de 0, 0, 242 et 212 affectations), puis décembre 2026 recréé, supprimé, récupéré (15:38) et supprimé de nouveau. **Toutes les archives sont conservées ; aucun mois n'est restauré automatiquement** — une récupération se fait seulement sur demande explicite, par l'action ci-dessus.

**Budget du mois prérempli depuis le budget de base** (migration 0016)
- Budget de base par marque (heures de travail effectif par mois) dans « Sites et marques » ; vide = non renseigné, rien n'est inventé.
- Chaque NOUVEAU mois reçoit ce budget pour les marques qui n'en ont pas encore ; une seule fois par marque et par planning, si bien qu'un ajustement (y compris un champ vidé) n'est jamais réécrasé. Plannings déjà générés ou calculés : jamais préremplis. Les brouillons existants reçoivent seulement les budgets manquants.
- Étape « Marques et sites » : champ numérique avec flèches et saisie directe, enregistré automatiquement ; « Budget de base : 88 h » ou « Ajusté pour ce mois · budget de base : 88 h » (avec « Revenir au budget de base ») ; sans base : « renseignez-le dans Sites et marques ». Budget total actif recalculé pendant la saisie. Le moteur utilise le budget enregistré du mois, selon le mode choisi (plafond strict ou objectif souple).
- Vérifié : 88 h → 96 h, conservé après actualisation et réouverture, utilisé par le moteur (plafond strict respecté), autres mois et budget de base inchangés (API et navigateur).
- Le budget appartient au MOIS : supprimer puis recréer le planning du mois reprend l'ajustement (96 h, jamais remplacé par les 88 h de base) ; un mois jamais saisi reçoit toujours la base (test API).
- « Revenir au budget de base » demande une confirmation (« Le budget de ce mois passera de 96 h à 88 h ») ; « Annuler » ne change rien (navigateur).

**Propositions de remplacement aux collaborateurs** (migration 0019)
- Le manager lance la proposition depuis « Voir les remplaçants » (bouton « Proposer » sur un candidat compatible) avec un délai de réponse (1 à 48 h). L'échéance affichée = maintenant + délai, jamais après le début du shift ; à moins de 5 min du début, la proposition est refusée (choix direct). Un candidat sans compte relié à sa fiche est signalé « Sans compte : proposition impossible ».
- Le collaborateur reçoit une notification interne et voit la proposition dans « Mon espace » : date, horaires, site, marque, échéance ; « Accepter » ou « Refuser » (motif facultatif). Il ne voit que les propositions qui lui sont adressées.
- **L'affectation actuelle reste en place pendant toute l'attente** ; refus, expiration, annulation ou caducité ne retirent jamais le titulaire (shift jamais laissé vacant). Refus ou expiration : le candidat suivant du classement est sollicité automatiquement (s'il est toujours compatible et a un compte) ; sinon « Aucun remplaçant n'a accepté », manager prévenu, titulaire conservé. Échéances traitées à l'heure exacte par l'ordonnanceur du worker (vérifié sans aucune lecture), et de nouveau à chaque lecture.
- Une seule demande ouverte et une seule proposition en attente par shift, garanties par des index uniques en base.
- Acceptation : shift, proposition, demande, affectation et collaborateur verrouillés (même ordre que toute modification du shift : pas d'interblocage) ; empreinte du shift et du titulaire comparée à celle du lancement ; toutes les contraintes actives revérifiées, sans dérogation possible par le collaborateur ; transfert en une seule opération (affectation verrouillée, plafond, rappels). Double clic ou second onglet : même résultat, rien de plus. Nouvelle absence ou autre shift accepté le même jour : acceptation refusée et expliquée, candidat suivant sollicité.
- Shift modifié, supprimé, déjà remplacé, planning archivé ou supprimé pendant l'attente : la demande devient caduque dès l'enregistrement de la modification ; le collaborateur et le manager sont prévenus, avec la raison ; l'ancienne proposition ne peut plus être appliquée.
- Le manager suit chaque demande (candidats sollicités, réponses, échéance) dans la fenêtre des remplaçants et dans le planning (« propositions en attente ») et peut l'annuler (confirmation).
- Brouillons et publication inchangés : l'acceptation modifie le planning en cours, jamais une version validée ou publiée ; le planning est signalé « modifié depuis la validation / publication », à republier par le circuit habituel ; le collaborateur en est informé.
- Historique : lancement, proposition, acceptation, refus, expiration, annulation, caducité, candidat non sollicité (avec la raison) et le transfert lui-même, avec auteur et date. Notifications : une par événement, persistantes, jamais répétées.
- Tests : API (acceptation, double clic, acceptations simultanées sur deux connexions, deux propositions du même jour acceptées en même temps, refus, expiration, épuisement, annulation, shift modifié ou réattribué pendant l'attente, nouvelle absence, sans compte, droits, version validée inchangée) et navigateur (proposition, double clic, refus, annulation).

**Intégration d'un ajout au planning existant** (migration 0017)
- Après la création d'une marque (« Sites et marques », y compris dans l'assistant) ou d'un collaborateur, si un planning en cours ou à venir (non archivé, avec des affectations) est concerné : « Comment souhaitez-vous intégrer cet ajout au planning de [mois année] ? ». Le mois, son statut et ses affectations sont affichés avant le choix ; plusieurs mois concernés : choix du mois, un seul à la fois. « Décider plus tard » ne modifie rien.
- « Recalculer tout le planning » : nouvelle génération du mois (paramètres conservés par le planning, besoins du mois, disponibilités, compétences, budgets, plafond, affectations verrouillées). Pour une marque, besoins, horaires, sites et budget du mois sont vérifiés avant : ce qui manque est listé, avec un lien vers « Sites et marques » et la saisie du budget du mois dans la fenêtre (préremplie avec le budget de base, modifiable). Versions « Avant intégration de … » (planning initial) et « Planning recalculé avec … » ; échec ou annulation : planning initial conservé actif, raison affichée ; jamais publié ; planning validé ou publié : confirmation explicite demandée.
- « Ajouter les shifts manuellement » : affectations conservées, aucune créée. Un collaborateur ajouté rejoint l'effectif de CE mois uniquement (autres mois intacts), sans quota inventé (seul son nombre de shifts attribués est affiché).
- Suivi persistant dans le planning (serveur, conservé après actualisation et reconnexion) : « Nuxe : 8 shifts attribués sur 10 — 2 restent à compléter. », heures couvertes et restantes, shifts à placer, placés sans collaborateur, affectés en conflit (jamais comptés comme couverts) ; liste des dates, horaires et sites ; « Placer et attribuer » crée le shift du besoin puis ouvre la fenêtre habituelle d'attribution (contrôles, confirmations, rappels « À régulariser »). « Tous les shifts de Nuxe sont attribués et sans conflit. » seulement si tout est couvert sans conflit ; l'alerte revient si la couverture redevient incomplète ; sans besoins : « Besoins à renseigner ». « Masquer le suivi » le retire de l'écran, le choix reste dans l'historique.
- Historique : « Intégration de la marque … au planning de … » (choix, auteur) et « Shift placé sans collaborateur ». Aucun calcul relancé ni autre mois modifié automatiquement.
- **Notifications de couverture** (migration 0018) : le suivi affiche en clair « Reste à attribuer : 2 shifts · 14 h ». À chaque modification enregistrée qui touche la couverture (attribution, retrait, échange, génération, besoins, horaires, absences, effectif, règles), quel qu'en soit l'auteur, la couverture est recalculée dans la même transaction ; une notification n'est créée qu'à un CHANGEMENT d'état : « Nuxe : tous les besoins de [mois] sont couverts » (tout attribué, sans conflit), puis « couverture de [mois] de nouveau incomplète » avec les shifts et heures restants. Rien n'est envoyé tant que l'état ne change pas (8 puis 9 sur 10, deuxième suppression…), ni au choix lui-même, ni pour un suivi masqué ; un conflit n'est jamais « couvert » ; besoins retirés : « Besoins à renseigner ». Destinataire : la personne qui a choisi l'ajout manuel. Nouvelle page « Notifications » (menu Planning, pastille des non lues) avec « Ouvrir le planning ». Vérifié après actualisation et nouvelle connexion (API et navigateur).

**SaaS**
- Rôles, cloisonnement RLS testé, périmètre d'un responsable de marque.
- Journal d'audit, export et effacement RGPD.

## Contexte conservé : planning et versions

| Donnée de génération | Au niveau du planning (`planning_periods.frozen_params`) | Dans **chaque version** (`schedule_versions.context`, depuis la migration 0011) |
|---|---|---|
| Collaborateurs et paramètres de fiche | ✅ (remplaçables par « Appliquer les paramètres actuels ») | ✅ figés |
| Effectif du mois (exclusions, contrats terminés, suppressions) | ✅ | ✅ figé |
| Disponibilités récurrentes | ✅ | ✅ figées |
| Absences datées et congés | lus en direct (données du mois) | ✅ figés à la date de la version |
| Besoins, horaires, shifts | lus en direct | ✅ figés |
| Budgets | lus en direct (par mois) | ✅ figés |
| Règles (repos, jours consécutifs, pauses, plafond) | ✅ | ✅ figées |
| Pondérations | ✅ (celles de la génération) | ✅ figées |
| Verrous | — | ✅ (ceux de la version) |
| Version du moteur | — | ✅ (`engine_version`) |
| Réglages du calcul (choix des paramètres, durée, pondérations exceptionnelles) | rapport du calcul | ✅ (calcul d'origine) |

- **Immuabilité** : un contexte n'est écrit qu'à la création de la version. Un déclencheur PostgreSQL interdit toute modification ultérieure du contexte et des affectations d'une version. Seule exception : l'effacement RGPD, marqué explicitement dans sa transaction.
- **Versions plus anciennes** : sans contexte figé, elles sont affichées « Contexte incomplet ». Aucune conformité n'est supposée.
- **Conformité**, colonne de la page Versions et détail consultable :
  - aux règles de création, évaluée sur le contexte figé de la version ;
  - aux règles actuelles, avec la date et l'heure de vérification.

  Les deux sont informatives : ni les affectations, ni le statut, ni les paramètres enregistrés ne sont modifiés. C'est vérifié par un test API.

## B. Partiellement réalisé (8 points, par priorité)

| Priorité | Élément | Ce qui manque |
|---|---|---|
| 1 | Performances | Au-delà de 150 collaborateurs : à 150, le niveau « engagements » manque de temps (ses critères sont reportés, jamais perdus). |
| 2 | Solutions multiples | Diversité mesurée et affichée entre simulations. |
| 3 | Temps rémunéré | Pauses payées distinguées dans les compteurs. |
| 4 | Espace collaborateur | Pas encore de réponse du collaborateur aux propositions de remplacement. |
| 5 | API | Documentation métier (OpenAPI générée). |
| 6 | Notifications | Dans l'application seulement ; l'e-mail dépend de la décision D2. |
| 7 | Comptes | Créés par l'administrateur ; les invitations dépendent de D2. |
| 8 | Environnements | Développement et tests séparés ; production à décider (D1). |

## C. Restant (8 chantiers, par priorité)

1. Tuteur et binôme avec portée « horaires qui se chevauchent » (la portée élargie s'applique aujourd'hui aux collaborateurs à séparer).
2. Espace collaborateur : réponse aux propositions de remplacement (congés, absences, indisponibilités hebdomadaires et échanges : faits).
3. Équité sur plusieurs mois pour les ouvertures et fermetures (week-ends et dimanches : faits).
4. Moteur : recherche à large voisinage (LNS), temps par niveau selon la taille, mesures au-delà de 150 collaborateurs et sur plusieurs mois.
5. Exploitation : reprise d'un calcul interrompu, surveillance, sauvegardes planifiées, secrets, production hors du Mac (dépend de D1).
6. Qualité : restauration de sauvegarde en intégration continue, tests aléatoires, objectifs de performance chiffrés.
7. Droits par agence ou équipe, prise en main guidée.
8. Import de plannings, synchronisation calendrier bidirectionnelle, paie et RH, prévisions de charge.

## D. Décisions qui vous reviennent

1. **Hébergement de production** : prestataire, région (Suisse ou UE) et budget.
2. **Envoi d'e-mails** (invitations, notifications) : service et coût.
3. **Assistant en langage naturel** : fournisseur et coût, s'il est souhaité.
4. **Validation juridique** des règles réglementaires par un spécialiste du droit suisse.
5. **Identités incertaines** (facultatif) : répartition prénom / nom de deux fiches ; les libellés actuels restent tels quels tant que vous ne la précisez pas.
6. **Couleur** : le rose est appliqué tel qu'il s'affiche dans votre image (profil Display P3). La valeur brute du fichier, #BB2757 lue en sRGB, serait plus terne. À confirmer après lecture de `docs/identite-visuelle.md`.

Déjà décidé (rappel) : les 106 tenants douteux et l'ancien tenant e2e de la base de développement sont conservés ; le mode sombre reste optionnel ; le plafond de 176 h, les minimums et maximums de jours et l'indépendance des plannings s'appliquent comme convenu.

## Préparation de la mise en production (avant tout déploiement public, décision D1)

1. Hébergement, région et budget (D1) ; secrets hors du dépôt ; sauvegardes planifiées et restauration vérifiée ; surveillance et alertes.
2. Plusieurs processus pour l'API (aujourd'hui un seul : les lectures lourdes simultanées se ralentissent entre elles, voir « Lenteurs et échecs intermittents »).
3. **Validation des performances avec plusieurs managers connectés et des modifications simultanées** (ajoutée le 19/11) :
   - scénario : N managers (au moins 5, puis 10 et 20) ouvrent le même mois et d'autres mois ; ils attribuent, transfèrent, échangent et retirent des shifts en même temps, consultent conflits, compatibilité et historique, pendant qu'une génération tourne ;
   - mesures : durée côté serveur (`Server-Timing`) et côté écran de chaque action, médiane et 95e centile ; requêtes lentes journalisées ; nombre de rechargements par modification ;
   - exactitude sous concurrence : aucune double affectation, conflits identiques à ceux recalculés seuls, refus « modifié par quelqu'un d'autre » quand deux managers touchent le même shift, plafond mensuel jamais dépassé, notifications de couverture envoyées une seule fois ;
   - critères d'acceptation chiffrés à fixer avec vous (par exemple : une attribution confirmée à l'écran en moins de 2 s au 95e centile avec 10 managers) ;
   - environnement : la pile de production elle-même (ou identique), jamais la base réelle ; données de test.
4. Reprise d'un calcul interrompu par un redémarrage ; e-mails (D2) si souhaités.

## Prochaines fonctionnalités : état et ordre proposé (19/11/2026)

| Ordre | Fonctionnalité | Existe déjà | Manque | Ce que cela change pour l'utilisateur |
|---|---|---|---|---|
| 1 | Réponse des collaborateurs aux remplacements (**fait le 19/11**) | Classement expliqué des remplaçants pour un shift (manager) ; demandes des collaborateurs (congé, absence, indisponibilité, échange) avec approbation | Envoi d'une proposition au collaborateur choisi, réponse acceptée / refusée dans « Mon espace », affectation seulement après acceptation et contrôles, relance du suivant en cas de refus | Le manager n'a plus à appeler chacun ; le collaborateur voit et accepte le shift proposé ; le planning se met à jour avec trace |
| 2 | Tuteur et binôme sur des horaires qui se chevauchent | Tuteur et binôme « même jour, même site » ; « à séparer » avec portée jour ou horaires qui se chevauchent | Portée « horaires qui se chevauchent » pour tuteur et binôme (moteur, contrôles manuels, écran de la fiche) | Un nouveau collaborateur n'est jamais seul sur sa plage horaire : le tuteur doit être présent EN MÊME TEMPS, pas seulement le même jour |
| 3 | Équité des ouvertures et fermetures sur plusieurs mois | Équilibre ouvertures / fermetures / week-ends dans le mois ; équité sur 3 mois pour week-ends et dimanches | Historique des ouvertures et fermetures des mois précédents pris en compte par le moteur, et affiché | Celui qui a souvent ouvert ou fermé le mois dernier en fait moins ce mois-ci |
| 4 | Moteur : recherche à large voisinage (LNS) et grands effectifs | Moteur hiérarchique vérifié ; critères non prouvés reportés, jamais perdus ; mesures jusqu'à 150 collaborateurs | Amélioration locale itérative, temps par niveau selon la taille, mesures au-delà de 150 et sur plusieurs mois | Meilleurs plannings dans le même temps de calcul pour les grandes équipes ; moins de « temps insuffisant » |
| 5 | Préparation de la mise en production | Pile isolée de tests, sauvegardes vérifiées, diagnostics de lenteur | Voir la section ci-dessus (dont la validation à plusieurs managers) ; dépend de D1 | Accès en ligne pour l'équipe, avec des temps de réponse mesurés et garantis |
| 6 | Temps rémunéré | Pause enregistrée (payée ou non) sur chaque affectation | Pauses payées distinguées dans les compteurs et exports | Heures payées exactes dans les totaux et la paie |
| 7 | Droits par agence ou équipe, prise en main guidée | Rôles et responsable de marque (périmètre par marque) | Périmètre par agence ou équipe ; parcours de démarrage | Chaque responsable ne voit et ne modifie que son équipe ; démarrage autonome d'un nouveau client |
| 8 | Intégrations | Exports PDF, Excel, CSV, ICS ; import des collaborateurs | Import de plannings, synchronisation calendrier dans les deux sens, paie et RH, prévisions de charge | Moins de double saisie avec les outils existants |

Remarques :
- **Tuteur et binôme (lot 2), consigne du 19/11** : distinguer un simple chevauchement d'horaires d'une présence du tuteur couvrant TOUTE la période qui nécessite un accompagnement. Un chevauchement partiel ne garantit pas que le nouveau ne sera jamais seul : la règle d'accompagnement exigera la couverture complète de sa plage (ou de la période définie), le chevauchement simple restant une option distincte, explicitement nommée.
- **Solutions multiples** : le moteur peut produire des variantes, mais les simulations ont été retirées de l'interface à votre demande ; rien n'est prévu tant que vous ne souhaitez pas les réafficher.
- E-mails (notifications, invitations) : dépendent de la décision D2 ; en attendant, tout passe par la page « Notifications ».
- Toujours exclu sans validation : les règles juridiques non validées (D4) ; la plateforme n'est pas présentée comme commercialisable.
