# Suivi du programme WFM : état réel

Mise à jour : 17 novembre 2026.

Une fonctionnalité n'est classée « terminée et vérifiée » que si une vérification exécutée la couvre. Les autres sont « partielles » (utilisables, avec des limites) ou « restantes ». Documents liés :
- `docs/moteur-evaluation.md` (choix du moteur, mesures) ;
- `docs/identite-visuelle.md` (rose de référence) ;
- `docs/backup-restore.md`.

## Résultats de tests (17/11/2026)

| Suite | Résultat | Environnement |
|---|---|---|
| Moteur, tests de correction (`packages/solver`) | **136 / 136** | local ; aussi **127 / 127 sous forte charge** (charge moyenne 44 sur 10 cœurs) et pendant la suite e2e |
| Moteur, mesures de performance (marqueur `perf`) | à part : `scripts/ops/perf_engine.sh` | conditions consignées dans `docs/mesures-moteur.md` |
| API (`apps/api`) | **155 / 155** | base PostgreSQL jetable par session (`planning_test_<pid>`) |
| Interface, unitaires, dont contrastes WCAG AA | **120 / 120** | Vitest |
| Navigateur e2e | **72 / 72** | pile Docker isolée (`infra/compose.e2e.yaml`, base `planning_e2e`) |
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
- Page « Équité » (3, 6 ou 12 mois) : travail effectif, jours, week-ends et dimanches de chacun, écart à la moyenne de l'équipe, détail des week-ends par mois (valeurs vérifiées contre les plannings).
- Plannings existants : ce nouveau critère ne s'applique pas à une régénération avec les paramètres conservés et n'apparaît pas comme une « différence ».

**Espace collaborateur et circuit d'approbation** (migration 0014)
- Depuis « Mon planning », un collaborateur relié à sa fiche demande un congé, une absence (journée ou partie de journée) ou un échange de shifts avec un collègue ; il suit le statut et peut annuler tant que rien n'est décidé.
- Échange : accord du collègue d'abord, puis décision du responsable ; l'approbation passe par le même contrôle qu'un échange fait à l'écran (alertes, dérogation réservée, plafond jamais dérogeable). Échange devenu impossible (planning modifié) : signalé, jamais appliqué.
- Page « Demandes » des responsables : shifts concernés affichés avant la décision ; un congé ou une absence approuvés ne retirent aucun shift (révision proposée si le planning est officiel). Un responsable ne traite jamais une demande qui le concerne.
- Notifications à chaque étape ; demandes incluses dans l'export et l'effacement RGPD.

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
| 2 | Performances | Au-delà de 150 collaborateurs : à 150, le niveau « engagements » manque de temps (ses critères sont reportés, jamais perdus). |
| 3 | Solutions multiples | Diversité mesurée et affichée entre simulations. |
| 4 | Temps rémunéré | Pauses payées distinguées dans les compteurs. |
| 5 | Espace collaborateur | Disponibilités récurrentes non modifiables par le collaborateur lui-même (demande à son responsable). |
| 6 | API | Documentation métier (OpenAPI générée). |
| 7 | Notifications | Dans l'application seulement ; l'e-mail dépend de la décision D2. |
| 8 | Comptes | Créés par l'administrateur ; les invitations dépendent de D2. |
| 9 | Environnements | Développement et tests séparés ; production à décider (D1). |

## C. Restant (8 chantiers, par priorité)

1. Tuteur et binôme avec portée « horaires qui se chevauchent » (la portée élargie s'applique aujourd'hui aux collaborateurs à séparer).
2. Espace collaborateur : modification des disponibilités récurrentes et réponse aux propositions de remplacement (congés, absences et échanges : faits).
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
5. **Identités incertaines** : répartition prénom / nom de deux fiches, en attente de votre confirmation (libellés actuels conservés).
6. **Tenants conservés** : 106 tenants douteux et l'ancien tenant e2e de la base de développement, conservés à votre demande.
7. **Couleur** : le rose est appliqué tel qu'il s'affiche dans votre image (profil Display P3). La valeur brute du fichier, #BB2757 lue en sRGB, serait plus terne. À confirmer après lecture de `docs/identite-visuelle.md`.

## Prochaines étapes (ordre de priorité)

1. Moteur : LNS et mesures plus larges.
2. Disponibilités récurrentes modifiables par le collaborateur (avec approbation).
