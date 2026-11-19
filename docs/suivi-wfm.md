# Suivi du programme WFM : état réel

Mise à jour : 18 novembre 2026.

Une fonctionnalité n'est classée « terminée et vérifiée » que si une vérification exécutée la couvre. Les autres sont « partielles » (utilisables, avec des limites) ou « restantes ». Documents liés :
- `docs/moteur-evaluation.md` (choix du moteur, mesures) ;
- `docs/identite-visuelle.md` (rose de référence) ;
- `docs/backup-restore.md`.

## Résultats de tests (19/11/2026)

| Suite | Résultat | Environnement |
|---|---|---|
| Moteur, tests de correction (`packages/solver`) | **137 / 137** (moteur inchangé dans ce lot) | local ; aussi **127 / 127 sous forte charge** (charge moyenne 44 sur 10 cœurs) et pendant la suite e2e |
| Moteur, mesures de performance (marqueur `perf`) | à part : `scripts/ops/perf_engine.sh` | conditions consignées dans `docs/mesures-moteur.md` |
| API (`apps/api`) | **176 / 176** | base PostgreSQL jetable par session (`planning_test_<pid>`) |
| Interface, unitaires, dont contrastes WCAG AA | **124 / 124** | Vitest |
| Navigateur e2e | **85 / 85** (suite complète, seule) | pile Docker isolée (`infra/compose.e2e.yaml`, base `planning_e2e`) |
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
- `e2e/integration.spec.ts`, attribution depuis le suivi de couverture (19/11) : un échec au premier passage, juste après la reconstruction des images Docker (charge moyenne d'environ 13). Le journal du serveur montre que la réponse à l'attribution (`manual-assign`, 200) est arrivée après le délai d'affichage de 5 s : même la modification faite au nettoyage du test avait déjà obtenu sa réponse. Hypothèse « premier chargement des modules après redémarrage » testée en redémarrant seulement l'API : **non confirmée** (938 ms). Quatre passages suivants réussis, de 923 à 1 177 ms. Cause **probable**, non démontrée : la charge de la machine. Le test enregistre désormais la durée réelle de l'attribution ; aucun délai n'a été allongé. À noter : l'attribution (≈ 1 s) est nettement plus lente que les lectures du planning (≈ 30 ms), piste de performance à examiner.
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
- Avril 2027 (tenant de démonstration, supprimé le 19/11 à 12:16 par le compte propriétaire) : archive de 237 affectations conservée, intacte ; **aucune récupération lancée** — elle se fait sur votre demande, par l'action ci-dessus.

**Budget du mois prérempli depuis le budget de base** (migration 0016)
- Budget de base par marque (heures de travail effectif par mois) dans « Sites et marques » ; vide = non renseigné, rien n'est inventé.
- Chaque NOUVEAU mois reçoit ce budget pour les marques qui n'en ont pas encore ; une seule fois par marque et par planning, si bien qu'un ajustement (y compris un champ vidé) n'est jamais réécrasé. Plannings déjà générés ou calculés : jamais préremplis. Les brouillons existants reçoivent seulement les budgets manquants.
- Étape « Marques et sites » : champ numérique avec flèches et saisie directe, enregistré automatiquement ; « Budget de base : 88 h » ou « Ajusté pour ce mois · budget de base : 88 h » (avec « Revenir au budget de base ») ; sans base : « renseignez-le dans Sites et marques ». Budget total actif recalculé pendant la saisie. Le moteur utilise le budget enregistré du mois, selon le mode choisi (plafond strict ou objectif souple).
- Vérifié : 88 h → 96 h, conservé après actualisation et réouverture, utilisé par le moteur (plafond strict respecté), autres mois et budget de base inchangés (API et navigateur).
- Le budget appartient au MOIS : supprimer puis recréer le planning du mois reprend l'ajustement (96 h, jamais remplacé par les 88 h de base) ; un mois jamais saisi reçoit toujours la base (test API).
- « Revenir au budget de base » demande une confirmation (« Le budget de ce mois passera de 96 h à 88 h ») ; « Annuler » ne change rien (navigateur).

**Intégration d'un ajout au planning existant** (migration 0017)
- Après la création d'une marque (« Sites et marques », y compris dans l'assistant) ou d'un collaborateur, si un planning en cours ou à venir (non archivé, avec des affectations) est concerné : « Comment souhaitez-vous intégrer cet ajout au planning de [mois année] ? ». Le mois, son statut et ses affectations sont affichés avant le choix ; plusieurs mois concernés : choix du mois, un seul à la fois. « Décider plus tard » ne modifie rien.
- « Recalculer tout le planning » : nouvelle génération du mois (paramètres conservés par le planning, besoins du mois, disponibilités, compétences, budgets, plafond, affectations verrouillées). Pour une marque, besoins, horaires, sites et budget du mois sont vérifiés avant : ce qui manque est listé, avec un lien vers « Sites et marques » et la saisie du budget du mois dans la fenêtre (préremplie avec le budget de base, modifiable). Versions « Avant intégration de … » (planning initial) et « Planning recalculé avec … » ; échec ou annulation : planning initial conservé actif, raison affichée ; jamais publié ; planning validé ou publié : confirmation explicite demandée.
- « Ajouter les shifts manuellement » : affectations conservées, aucune créée. Un collaborateur ajouté rejoint l'effectif de CE mois uniquement (autres mois intacts), sans quota inventé (seul son nombre de shifts attribués est affiché).
- Suivi persistant dans le planning (serveur, conservé après actualisation et reconnexion) : « Nuxe : 8 shifts attribués sur 10 — 2 restent à compléter. », heures couvertes et restantes, shifts à placer, placés sans collaborateur, affectés en conflit (jamais comptés comme couverts) ; liste des dates, horaires et sites ; « Placer et attribuer » crée le shift du besoin puis ouvre la fenêtre habituelle d'attribution (contrôles, confirmations, rappels « À régulariser »). « Tous les shifts de Nuxe sont attribués et sans conflit. » seulement si tout est couvert sans conflit ; l'alerte revient si la couverture redevient incomplète ; sans besoins : « Besoins à renseigner ». « Masquer le suivi » le retire de l'écran, le choix reste dans l'historique.
- Historique : « Intégration de la marque … au planning de … » (choix, auteur) et « Shift placé sans collaborateur ». Aucun calcul relancé ni autre mois modifié automatiquement.

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

## Prochaines étapes (ordre de priorité)

1. Moteur : LNS et mesures plus larges.
2. Propositions de remplacement envoyées aux collaborateurs, avec leur réponse.
