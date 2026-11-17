# Suivi du programme WFM : état réel

Mise à jour : 17 novembre 2026.

Une fonctionnalité n'est classée « terminée et vérifiée » que si une vérification exécutée la couvre. Les autres sont « partielles » (utilisables, avec des limites) ou « restantes ». Documents liés :
- `docs/moteur-evaluation.md` (choix du moteur, mesures) ;
- `docs/identite-visuelle.md` (rose de référence) ;
- `docs/backup-restore.md`.

## Résultats de tests (17/11/2026)

| Suite | Résultat | Environnement |
|---|---|---|
| Moteur (`packages/solver`) | **124 / 124** | local |
| API (`apps/api`) | **134 / 134** | base PostgreSQL jetable par session (`planning_test_<pid>`) |
| Interface, unitaires, dont contrastes WCAG AA | **119 / 119** | Vitest |
| Navigateur e2e | **60 / 60** | pile Docker isolée (`infra/compose.e2e.yaml`, base `planning_e2e`) |
| ruff, TypeScript, ESLint | sans erreur | |

Intermittences connues : deux tests e2e dépendent du moment de mesure (« mouvement réduit », alignement après animation). Le second est corrigé ; le premier passe 3 fois sur 3 lorsqu'il est lancé seul.

## Vérifications ciblées

| Exigence | Preuves exécutées |
|---|---|
| **Plafond de 176 h** (travail effectif, tous sites et marques, mois civil) | Moteur : plafond strict (sans plafond, 26 shifts soit 208 h ; avec, 22 shifts soit 176 h). Heures d'une période voisine du même mois comptées. Shift de nuit rattaché au mois de son début. Dépassement fixé conservé, jamais aggravé. API : génération ; ajout, transfert, réaffectation, changement d'horaire et restauration refusés au-delà ; réduction d'un dépassement permise ; réoptimisation locale d'un planning qui dépasse déjà. E2E : transferts refusés avec la règle affichée (« … travaillerait 184 h »). |
| **Minimum et maximum de jours par mois** (indépendants, « Pas de préférence », une journée comptée une fois) | Moteur : maximum strict avec deux shifts le même jour ; minimum obligatoire ; minimum impossible bloqué avec la raison (jours possibles, plafond, jours consécutifs, minimums incompatibles entre eux). API : incohérences refusées (minimum supérieur au maximum, minimum incompatible avec le plafond) ; exception du mois sans effet sur les autres mois ; blocage signalé avant génération. Unitaires et e2e : formulaires. |
| **Indépendance des plannings et paramètres conservés** | API : une fiche modifiée ne crée aucune incompatibilité dans un planning existant. Générer un autre mois ne touche pas le premier. « Appliquer les paramètres actuels » est explicite et ne déplace aucune affectation. Pondérations de la génération conservées. Collaborateur ajouté ou supprimé après coup : aucun effet rétroactif. E2E : fiche modifiée, novembre inchangé, détail « si appliqués ». Démo : novembre identique à la sauvegarde du 17/11 à 8 h 22. |
| **Vérificateur indépendant** (Python, sans CP-SAT) | Exécuté après le calcul, sur les données relues et sur le planning enregistré. Plan rejeté si une contrainte est violée (test de solveur volontairement faussé). Donnée modifiée pendant le calcul : plan rejeté. Également après un ajout, un transfert, une restauration ou une simulation appliquée. |
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
- Vues mois, planning général, jour, collaborateur, marque/site.
- Recherche, filtres, annuler et rétablir, compteurs.
- Exports PDF, Excel, CSV et ICS.

**SaaS**
- Rôles, cloisonnement RLS testé, périmètre d'un responsable de marque.
- Journal d'audit, export et effacement RGPD.

## B. Partiellement réalisé

| Élément | Ce qui manque |
|---|---|
| Solutions multiples | Simulations comparées ; diversité des solutions non mesurée. |
| Performances | Mesurées jusqu'à 150 collaborateurs. À 150, le niveau « engagements » manque de temps : ses critères sont reportés au niveau suivant, jamais perdus. |
| Relations entre collaborateurs | Portée « même jour, même site » seulement ; « horaires qui se chevauchent » et « même jour, tous sites » manquent. |
| Contexte de génération | Conservé dans le planning et dans le rapport du calcul ; pas encore recopié dans chaque version, ni la version du moteur. |
| Absence sur un planning publié | Impact et remplaçants disponibles ; pas de proposition de révision automatique ni de notification dédiée. |
| Vérificateur | Indépendant du solveur, mais partage deux petites fonctions avec le générateur (pause exigée, catégorie horaire). |
| Notifications | Dans l'application seulement, sans e-mail ni push. |
| Comptes | Créés par l'administrateur, sans invitation par e-mail. |
| Espace collaborateur | Consultation du planning publié seulement. |
| API | OpenAPI générée ; documentation métier à écrire. |
| Environnements | Développement et tests séparés ; aucune production. |
| Exports PDF et Excel | Fonctionnels, sans la nouvelle identité visuelle (en-têtes gris). |
| Temps rémunéré | Pauses payées non distinguées dans les compteurs. |

## C. Restant

1. Badge de conformité aux règles actuelles dans la liste des versions ; contexte de génération dans chaque version.
2. Échange réciproque et duplication de shifts, modifications groupées, tous vérifiés par le même contrôle.
3. Absences partielles, temps de déplacement entre sites, couverture pendant les pauses, horaires obligatoires par collaborateur.
4. Vue semaine, vue client.
5. Suivi de l'équité sur plusieurs mois.
6. Moteur : recherche à large voisinage (LNS), temps par niveau selon la taille, mesures au-delà de 150 collaborateurs et sur plusieurs mois, diversité des solutions.
7. Espace collaborateur : disponibilités, congés, propositions d'échange, réponses aux remplacements, avec circuit d'approbation.
8. Droits par agence ou équipe, invitations, prise en main guidée.
9. Import de plannings ; synchronisation calendrier bidirectionnelle ; paie et RH ; prévisions de charge.
10. Exploitation : reprise d'un calcul interrompu par l'arrêt du worker, surveillance, gestion des secrets, sauvegardes planifiées, infrastructure de production hors du Mac.
11. Restauration de sauvegarde en intégration continue, tests aléatoires (fuzzing), objectifs de performance chiffrés.

## D. Décisions qui vous reviennent

1. **Hébergement de production** : prestataire, région (Suisse ou UE) et budget.
2. **Envoi d'e-mails** (invitations, notifications) : service et coût.
3. **Assistant en langage naturel** : fournisseur et coût, s'il est souhaité.
4. **Validation juridique** des règles réglementaires par un spécialiste du droit suisse.
5. **Identités incertaines** : répartition prénom / nom de deux fiches, en attente de votre confirmation (libellés actuels conservés).
6. **Tenants conservés** : 106 tenants douteux et l'ancien tenant e2e de la base de développement, conservés à votre demande.
7. **Couleur** : le rose est appliqué tel qu'il s'affiche dans votre image (profil Display P3). La valeur brute du fichier, #BB2757 lue en sRGB, serait plus terne. À confirmer après lecture de `docs/identite-visuelle.md`.

## Prochaines étapes (ordre de priorité)

1. Versions : contexte de génération et badge de conformité aux règles actuelles.
2. Échange réciproque et duplication de shifts.
3. Absences partielles et portée des relations.
4. Moteur : LNS, temps par niveau selon la taille, mesures plus larges.
5. Espace collaborateur et circuit d'approbation.
6. Production, une fois les décisions 1 et 2 prises.
