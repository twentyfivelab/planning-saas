# Planning SaaS — planification automatique multi-tenant

Application de planification sous contraintes (OR-Tools CP-SAT) pour entreprises multi-marques / multi-sites.
Fuseau : **Europe/Zurich**. Interface en français (catalogue i18n extensible).

> **Aide à la décision, pas un conseil juridique.** Les valeurs légales (repos 11 h, 6 jours consécutifs) sont des
> références initiales, versionnées et marquées « à valider » : faites-les valider par un spécialiste du droit suisse
> avant toute utilisation en production.

## ⚠️ Statut légal : non commercialisable en l'état
Règles exécutées par le solveur, comme **valeurs de référence à faire valider** : repos quotidien (défaut 11 h), maximum de
jours consécutifs (défaut 6, règle interne) et, si elles sont activées dans le référentiel juridique, durée maximale
hebdomadaire et pauses minimales. **Non exécutés** : travail de nuit, travail du dimanche et repos compensatoires, travail
supplémentaire au sens légal, jeunes travailleurs, catégories particulières, dérogations conventionnelles. L'application
**ne doit pas être commercialisée ni utilisée en production** pour des plannings réels tant que ces règles ne sont pas
implémentées et validées par un spécialiste du droit suisse.
Ce statut est répété dans l'interface, les diagnostics (`LEGAL_REVIEW`) et l'export Excel (« Hypothèses »).

## Architecture

```
apps/web         Next.js 15 + TypeScript + Tailwind (glassmorphism, clair/sombre, responsive)
apps/api         FastAPI + SQLAlchemy 2 + Alembic ; sessions serveur, RBAC, audit, exports, imports
packages/solver  Moteur CP-SAT pur Python (aucune dépendance DB) : SolverInput -> SolverResult
infra/           compose.yaml (postgres, redis, api, worker RQ, web) + Dockerfiles
docs/            simulation, paramétrage légal, sauvegarde, conservation, limites
```

Décisions : un seul backend Python (API + solveur dans le même langage, OpenAPI natif) ; le solveur reste isolé
derrière `planning_solver.solve(SolverInput)` et peut être extrait en service séparé. Optimisations asynchrones
via Redis/RQ (`OPT_EXECUTION=rq`), idempotentes par en-tête `Idempotency-Key`.
Isolation multi-tenant : `tenant_id` partout + **PostgreSQL Row-Level Security** (`FORCE`), rôle applicatif
non-superuser ; l'API positionne `app.tenant_id` par transaction. Un id d'un autre tenant renvoie 404.

Modèle de temps : présence (09:00–18:00 = 9 h), pause non travaillée (1 h), travail effectif (8 h, base des budgets),
imputation aux marques (`BrandAllocation`, ex. 4 h Cellcosmet + 4 h Nuxe pour **une** affectation de 8 h).

## Installation et lancement (Docker)

```bash
cp .env.example .env            # puis remplacer les mots de passe (aucun secret réel dans le dépôt)
docker compose -f infra/compose.yaml --env-file .env up -d --build
```
La commande de l'API applique les migrations (`alembic upgrade head`) au démarrage.
Données de démonstration (novembre 2026) :
```bash
docker compose -f infra/compose.yaml --env-file .env exec -e DEMO_PASSWORD='<choisir>' api python -m app.seed
# sans DEMO_PASSWORD, un mot de passe aléatoire est généré et affiché une seule fois
```
Comptes : `owner|manager|planner|auditor|collaborateur@demo.example` (argument optionnel : un autre domaine).
- Web : http://localhost:3000 — API : http://localhost:8000 — OpenAPI : http://localhost:8000/docs

## Développement local (sans conteneurs pour le code)
```bash
docker compose -f infra/compose.yaml --env-file .env up -d postgres redis
python3.12 -m venv .venv && .venv/bin/pip install -r apps/api/requirements-dev.txt
set -a; . ./.env; set +a
cd apps/api && PYTHONPATH=.:../../packages/solver ../../.venv/bin/alembic upgrade head
PYTHONPATH=.:../../packages/solver ../../.venv/bin/uvicorn app.main:app --reload
cd ../web && npm ci && npm run dev
```

## Tests et qualité
```bash
.venv/bin/ruff check apps/api packages/solver
.venv/bin/python -m pytest packages/solver apps/api          # unitaires, solveur, intégration PostgreSQL (unitaires, solveur, intégration)
cd apps/web && npm run lint && npm run typecheck && npm test && npm run build
E2E_EMAIL=owner@e2e.example E2E_PASSWORD=<mdp> npx playwright test   # pile Docker lancée, tenant de test dédié
```
Les tests navigateur modifient et régénèrent les plannings du compte utilisé : ils exigent un tenant dédié (`@e2e.example`), jamais celui que l'on consulte.
Création : `python -c "from app.seed import seed; print(seed(tenant_name='Tests automatiques e2e', domain='e2e.example'))"` depuis `apps/api`, puis une génération de novembre 2026.
Les tests d'intégration exigent PostgreSQL (compose) et migrent via `alembic upgrade head`.
Couverture notable : total 1 752 h ; 90/60/8 shifts ; présence/pause/effectif ; repos 11 h ; 6 jours max ;
Sabrina ; Jane/Chloé ; Ying ≤ 3 j/sem ; verrouillage + réoptimisation partielle ; diagnostic d'infaisabilité ;
Lindt/Toblerone ; aucun contrat inventé ; isolation inter-tenants (API **et** RLS en SQL brut) ; rôles ; CSRF ;
rate-limit ; exports filtrés.
CI : `.github/workflows/ci.yml` (ruff, migrations, pytest, eslint, tsc, vitest, build).

## Design system (apps/web)
Tokens centralisés dans `apps/web/src/styles/tokens.css` (couleurs clair/sombre, typographie, espacements, rayons, ombres,
niveaux de verre, palette de 10 marques) ; composants dans `src/styles/components.css` et `src/components/ui/`
(Button, Badge, Card, Field, Modal basée sur `<dialog>`, Toast, Tooltip, Skeleton, EmptyState, ErrorState, Callout,
Ring/BarList, ShiftCard). Thème automatique/clair/sombre posé avant hydratation. Le flou est limité aux grands panneaux ;
repli opaque sans `backdrop-filter`, avec `prefers-reduced-transparency` et en contraste forcé ; `prefers-reduced-motion`
respecté. Les contrastes WCAG AA des tokens sont vérifiés par `src/styles/tokens.test.ts`.

**Réaffectation sécurisée** : tout changement de collaborateur (fiche, sélecteur du mode Jour, glisser-déposer) ouvre une
confirmation obligatoire (`useReassign`, seul point d'appel de `PUT /assignments/{id}` côté web, garde-fou testé). Focus initial
sur « Annuler », Échap/clic extérieur = annulation, aucun « ne plus demander ». « Annuler/Rétablir » rejouent une réaffectation déjà confirmée.

## Sécurité (résumé)
Argon2id ; cookie de session `HttpOnly` + `SameSite=Lax` (+ `Secure` via `SESSION_COOKIE_SECURE=true` en HTTPS) ;
sessions serveur ; CSRF (double jeton) ; RBAC par rôle (propriétaire, admin, manager, planificateur, collaborateur,
auditeur) ; validation Pydantic stricte (`extra=forbid`) ; limitation de débit login/inscription ; journal d'audit
append-only (UPDATE/DELETE révoqués) ; imports limités (2 Mo, 2 000 lignes, .csv/.xlsx) ; neutralisation des formules
CSV/Excel ; aucune donnée sensible dans les logs ni les erreurs ; endpoints RGPD/LPD d'accès et d'effacement
(`/data-subject/{id}`). Voir `docs/backup-restore.md` et `docs/retention.md`.

## Utilisation métier
1. Saisir marques, sites, collaborateurs, **contrats** (formulaire : début/fin, taux, heures, min/max, heures sup.),
   disponibilités, congés, modèles de shifts, besoins, budgets, règles.
2. *Génération* : vérification des données → paramètres/poids → calcul asynchrone → diagnostic.
3. *Planning* : vues mois/semaine/jour/collaborateur/marque, glisser-déposer, modification d'horaire,
   verrouillage, annuler/rétablir, conflits immédiats ; *Réoptimisation partielle* conserve les verrous.
4. *Versions* : enregistrer, comparer, publier. Une version issue d'une **simulation exploratoire** ne peut pas être publiée.
5. *Import/Export* : PDF, Excel (Planning, Collaborateurs, Budgets, Alertes, Hypothèses), CSV, ICS par collaborateur.

## Horaires, fiches collaborateurs et dimanches
**Horaires autorisés** (fournis, 1 h de pause non travaillée = 8 h effectives) : Ploom GVA3 06–15 / 10–19 / 12–21 ; Ploom Pilar 06–15 / 11–20 ;
Ploom GVA9 07–16 / 12h30–21h30 ; Cailler, Lindt, Toblerone et marques d'alcool 09–18 ; Valmont 08–17 / 09–18 / 10–19 ; Cartier 08–17 ;
Nuxe/Cellcosmet 09–18. Ils sont enregistrés comme modèles de shifts à portée (`scope_type` : site, marque ou groupe) et proposés lors de la
modification d'un shift ; seul un administrateur peut déroger (tracé dans le journal d'audit). Aucune marque d'alcool n'étant nommée,
aucune n'est créée (groupe `ALCOOL` prêt).

**Fiche collaborateur** (colonnes de `employees`, transmises au moteur) :
- *Jours maximum* : nombre (1–7 par semaine, 1–31 par mois) + période ; contrainte dure, y compris sur les semaines à cheval sur deux périodes
  (les jours déjà planifiés dans une période voisine sont comptés ; sans planning voisin, le manque est signalé, jamais supposé).
- *Préférence horaire* : matin (début avant 9 h), middle shift (9 h–11 h 59), soir (dès 12 h), souple (pénalité) ou stricte (contrainte dure).
  Une boutique à horaire unique reste ouverte à tous.
- *Dimanches* : 0 à 5 par période, en *maximum* (plafond dur) ou *objectif exact* (plafond dur + manque pénalisé). Tout quota attribué compte comme dimanche **réservé** dans le compteur (mode par défaut : objectif exact).
- « Pas de préférence » = aucune limite (valeur `null`). Rien n'est appliqué par défaut.

**Marques et boutiques par collaborateur** (fiche → « Marques et boutiques autorisées ») : sélection multiple (Ploom regroupe GVA3, Pilar et GVA9, chaque
boutique étant cochable séparément) avec une priorité *prioritaire / secondaire / renfort* (coût croissant dans l'objectif). Une marque non cochée n'est
**jamais** attribuée : le moteur, la réaffectation manuelle (refusée) et l'ajout manuel la respectent. Les horaires proposés suivent les marques cochées
(`GET /brand-schedules`) ; l'ajout d'un shift (bouton « + » d'une case vide de la vue semaine) ne propose que les marques autorisées puis les horaires de
la marque choisie, vérifie l'indisponibilité et la double affectation, et crée une affectation **verrouillée**.

**Jours d'indisponibilité** (fiche → calendrier) : un clic bascule un jour, Maj + clic sélectionne une plage ; enregistrement automatique
(`PUT /employees/{id}/unavailable-dates`) ; les règles récurrentes et congés approuvés sont affichés hachurés. Le moteur ne planifie jamais un jour bloqué.

**Enregistrement automatique et synchronisation** : tous les champs de la fiche s'enregistrent dès qu'ils sont cohérents ; un bus d'invalidation recharge
compteurs, compatibilité et planning dans tous les écrans, sans rechargement de page. Si un planning existe déjà, `GET /periods/{id}/compatibility` signale
les incompatibilités (règles obligatoires et préférences) sans rien modifier ; la réoptimisation exige une confirmation, conserve les affectations
verrouillées et affiche un comparatif avant/après (refusée avec explication si un verrou est incompatible).

## Création et gestion des plannings mensuels
- **« + Générer un nouveau planning »** (page Planning, page Génération, et « + » de l'historique latéral) ouvre un assistant en 6 étapes, enregistré à chaque action
  (brouillon repris là où on s'est arrêté, `planning_periods.wizard_step`) : Période → Collaborateurs → Paramètres individuels → Marques et sites → Vérification → Génération.
  Choisir un mois ne génère rien ; un mois déjà planifié est signalé (« Ouvrir le planning » / « Modifier ses paramètres ») et n'est jamais recalculé sans confirmation.
- **Effectif du mois** (`period_employees`, `GET/PUT /periods/{id}/roster`) : tous les actifs cochés par défaut ; décocher exclut du mois uniquement (fiche, historique,
  autres mois intacts) ; le moteur ne lui attribue aucun shift et une affectation manuelle est refusée. « Contrat terminé » (tous les contrats finis avant le mois) et « Inactif »
  sont des états permanents, distincts, non sélectionnables.
- **Paramètres individuels** : la fiche existante est réutilisée telle quelle. Permanents : marques, préférences horaires, jours maximum habituels. Mensuels : indisponibilités
  datées, dimanches, **exception de jours maximum** (`employee_month_params.max_days_set`). Après un changement permanent, la fiche liste les plannings existants devenus
  incompatibles (`GET /employees/{id}/impact`) sans rien modifier.
- **Marques et budgets du mois** (`period_brands`, `GET /periods/{id}/brands`, `PUT /periods/{id}/brands/{code}`) : activation, budget (plafond strict ou objectif souple)
  propre au mois, référence du mois précédent affichée mais jamais imposée, besoins réels (heures obligatoires/optionnelles, jours, shifts, horaires, sites) et écarts signalés.
- **Sites et marques** (page *Sites et marques*, `/catalog`) : ajout de sites et de marques, renommage (le code reste l'identifiant stable : affectations conservées),
  archivage à partir d'un mois (les mois antérieurs restent intacts), « animations » marque + site + horaire + jours + nombre de personnes (`staffing_requirements.headcount`),
  horaires propres à la combinaison marque@site, autorisation de collaborateurs. Toute modification d'une animation crée une **version datée** (`valid_from` / `valid_to`) :
  les mois précédents gardent leur configuration. Sites actifs par mois : `period_sites`.
- **Vérification avant génération** (`GET /periods/{id}/readiness`) : récapitulatif (effectif, marques, sites, budget, shifts, dimanches, indisponibilités, contraintes) et incohérences
  (budgets manquants ou insuffisants, marque sans collaborateur autorisé, collaborateur sans marque active, verrous sur des exclus, affectations sur un site/une marque désactivés).
- **Historique des plannings** (barre latérale) : tous les mois créés, avec un statut **déduit des données** : Brouillon (aucune affectation), Généré, Validé (version publiée),
  Archivé (`POST /periods/{id}/archive` : consultable, non modifiable ; désarchivable). Un brouillon jamais calculé peut être supprimé ; un planning généré, jamais.
- Après génération, toutes les modifications existantes restent disponibles (ajout/transfert manuel, indisponibilités, préférences, budgets, sites, pondérations, réoptimisation
  partielle, verrous) ; aucune modification de paramètre ne relance une génération automatiquement.

## Plusieurs mois, paramètres mensuels, pondérations et gestion manuelle
- **Un planning indépendant par mois** : le sélecteur de mois/année (listes + flèches ; changement d'année automatique) est présent sur le planning général,
  le planning individuel et la génération ; le mois choisi est mémorisé. `POST /periods/ensure` ouvre (ou crée) le mois sans jamais toucher aux autres ;
  générer décembre ne modifie ni novembre ni janvier. Un mois déjà planifié propose d'être ouvert ou réoptimisé (jamais écrasé en silence).
- **Calendrier et besoins calculés** (`GET /calendar?year=&month=`) : jours, samedis, dimanches, jours d'ouverture des marques, shifts à pourvoir, budgets du mois,
  total des shifts du dimanche (= besoins configurés × nombre de dimanches : 7 × 5 = 35 en novembre 2026, 7 × 4 = 28 en décembre 2026). Aucune logique propre à un mois.
  Sans budget pour le mois, le moteur le signale (`BRAND_BUDGET_MISSING`) et n'en invente jamais ; « Copier les budgets du mois précédent » est une action explicite.
- **Paramètres permanents** (conservés d'un mois à l'autre) : marques/boutiques autorisées, préférences horaires, priorités, horaires des marques, règles générales,
  pondérations. **Paramètres mensuels** : indisponibilités et congés (datés), budgets, besoins ponctuels et **quota de dimanches** (table `employee_month_params`,
  `PUT /employees/{id}/month-params/{AAAA-MM}`) : modifier décembre ne change jamais novembre. L'ancienne valeur « globale » de la fiche est reportée sur les mois déjà planifiés lors de la première saisie mensuelle.
- **Frontière entre deux mois** : le moteur et la vérification consultent les shifts des périodes voisines (repos 11 h, jours consécutifs, semaines à cheval).
- **Paramètres → Pondération de l'algorithme** (`/settings`, `GET/PUT /settings/weights`, `POST /settings/weights/reset`) : 9 critères réglables de 0 à 100 (curseur + saisie,
  enregistrement automatique) plus des réglages avancés. Poids du moteur = poids par défaut × 2^((valeur − défaut)/20) : +20 points doublent l'influence, 0 la supprime.
  Enregistrées en base (`constraint_definitions.code = weights_ui`), transmises au solveur à chaque génération et réoptimisation, jamais sur les contraintes strictes.
  Le résultat expose le coût par critère (`criteria_scores`) pour vérifier ce qui a influencé le choix. Critères réellement branchés : équité, préférences horaires, priorité de marque,
  priorité individuelle (poids d'allocation), objectifs horaires (budgets), équilibrage des dimanches, alternance matin/soir, famille Mila/Abdu, équilibrage des jours.
- **Planning général** : tous les jours du mois en colonnes, colonne des noms et en-têtes fixes, défilement horizontal (trackpad, souris, tactile, clavier, flèches), position conservée entre les vues.
- **Planning individuel** : clic sur une date → fenêtre de tous les shifts du jour (marque, boutique, horaire, titulaire, statut, alertes) ; attribution d'un shift libre ou
  **transfert atomique** d'un shift occupé (`POST /periods/{id}/manual-assign`) avec alertes détaillées (règle, valeur autorisée, valeur atteinte, conséquence), « Accepter quand même » /
  « Annuler », dérogations tracées (date, utilisateur, motif), détection des modifications concurrentes (`expected_from`) et resynchronisation automatique entre managers (`GET /revision`).
  Un shift n'a jamais deux titulaires (contrainte d'unicité en base).
- **Qui approuve une dérogation** : uniquement un propriétaire, un administrateur ou un manager (`app/approval.py`), y compris pour une simple préférence ;
  jamais la personne concernée (un responsable lié à la fiche du collaborateur visé ou du titulaire actuel ne peut pas valider sa propre exception) ;
  un collaborateur n'a aucun droit de modification. Les règles non dérogeables restent bloquées pour tous. Chaque dérogation est tracée (date, utilisateur, rôle, motif).
- **Temps réel** : toute transaction validée qui écrit dans le journal d'audit publie un message Redis (`planning:changes:<tenant>`) ; le navigateur est abonné au flux
  Server-Sent Events `GET /events` et se recharge en moins d'une seconde (mesuré : 150–250 ms en local). Rien n'est annoncé pour une transaction annulée. Si le flux est coupé,
  l'interrogation de `/revision` (6 s) prend le relais. Le rechargement attend la fermeture d'une fenêtre ouverte.
- **Report des quotas de dimanches historiques** (`migrate_legacy_quota`) : une seule fois par collaborateur, copie exacte (quota et mode) vers les seuls mois planifiés
  sans valeur mensuelle ; valeurs mensuelles, affectations et versions publiées jamais modifiées ; valeur historique conservée (`employees.sunday_quota` + `sunday_quota_migrated_at`) ;
  contrôle avant/après (annulation complète si une valeur effective changeait) ; tracé dans l'audit (`employee.sunday_quota_migration`). Modifier le quota d'un mois publié
  ne change pas la version publiée et affiche un avertissement.

**Dimanches de novembre 2026** : GVA3 3 + Pilar 2 + GVA9 2 = 7 shifts × 5 dimanches (1, 8, 15, 22, 29) = **35 shifts**. Le compteur
(`GET /periods/{id}/sunday-summary`, recalculé côté client en direct) distingue *à couvrir*, *réservés* (quotas exacts), *planifiés* (affectations
réelles) et *restant à attribuer* (à couvrir − réservés) ; il alerte si les quotas ne peuvent pas tout couvrir.
Chaque planning est contrôlé par un vérificateur indépendant ; un planning qui enfreint une contrainte dure n'est jamais enregistré.

## Plateforme de Workforce Management

Pensée pour une société de placement : plusieurs clients, marques, sites et missions. Tout s'ajoute à l'existant (assistant mensuel, gestion manuelle, pondérations).

**Clients et missions** (`/clients`) : clients, responsables, contrats commerciaux, tarifs ; qualifications et langues. Une mission (client, marque, sites, dates, jours, horaire, personnes, qualifications, heures commandées, priorité) reste en brouillon jusqu'à sa confirmation, puis ses besoins sont planifiés avec ceux des animations permanentes. Modification, annulation et renouvellement signalent les shifts concernés, sans rien retirer sans décision du manager.

**Moteur** (`packages/solver`) :
- une variable de décision par affectation admissible ; le préfiltrage écarte d'emblée les autres (`context.py`) ;
- optimisation hiérarchisée (`SolverConfig.hierarchical`, réglable dans Paramètres) : contraintes dures, puis couverture (pondérée par la priorité), puis engagements (objectifs contractuels, quotas exacts, budgets souples), puis tous les autres critères. Chaque niveau est figé avant le suivant ; « optimal » n'est annoncé que si tous les niveaux sont prouvés ;
- évaluateur indépendant (`objective.py`) : recalcule sans CP-SAT le coût exact d'un planning ; un test vérifie qu'il retrouve la valeur du solveur à l'optimum ;
- vérificateur indépendant (`validator.py`) : recalcule aussi heures, pauses et imputations ; un plan en violation n'est jamais enregistré.

**Décisions** : remplaçants classés par la variation réelle du coût (`GET /shifts/{id}/replacements`) ; explication d'une affectation, sans cause inventée (`GET /assignments/{id}/explain`) ; absence imprévue avec trois réponses, du remplacement simple à la réoptimisation complète (`POST /periods/{id}/absences`, `POST /periods/{id}/local-reoptimize`) ; simulations comparables, sans écriture tant qu'elles ne sont pas appliquées (`/simulations`).

**Cycle de vie** (`/versions`) : Brouillon, Généré, En cours de validation, Validé, Publié, Archivé. Les versions sont des copies immuables, créées automatiquement avant et après chaque remplacement d'affectations ; la restauration est réversible. Un planning validé ou publié n'est jamais remplacé sans confirmation. La publication notifie une fois chaque collaborateur concerné ; il ne voit que les versions publiées (`/me`).

**Conservation des versions automatiques** (Paramètres, `GET/PUT /settings/version-retention`, 20 par mois par défaut, âge maximal facultatif) : s'applique à chaque génération ou sur demande. Jamais les versions manuelles, soumises, validées, publiées ou remplacées, ni celles d'un mois archivé ; la plus récente reste toujours ; chaque retrait est tracé. Les propriétaires et administrateurs peuvent aussi retirer les copies automatiques d'un mois ou remettre un mois à zéro (`/versions`), refusé dès qu'une version officielle ou des heures validées existent.

**Vérificateur indépendant** : il s'exécute sur tout planning produit, optimal, valide, partiel, interrompu, simulé ou réoptimisé, à trois moments : sur le résultat du solveur, sur les données relues après le calcul (une absence saisie pendant le calcul fait rejeter le plan), puis sur le planning enregistré, dans une transaction annulée en cas de violation nouvelle. Le détail est conservé dans le rapport du calcul (`verification`). Sans planning produit, rien n'est enregistré et le rapport le dit.

**Suivi** : heures réelles distinctes du planning, validées par un responsable autre que la personne concernée (`/time`) ; heures, coûts, facturation et marges par client, marque, mission et site, un montant inconnu restant « Non renseigné » (`/finance`) ; exports paie, facturation et couverture ; tableau de bord de pilotage.

**Référentiel juridique** (`/rules`) : modèles sourcés (SECO) à activer, règles versionnées par régime, validation nominative (`legal.review`). Rien n'est actif d'office.

**Rôles** : propriétaire, administrateur, manager, planificateur, responsable de marque (limité à ses marques, `users.scope`), collaborateur (son planning publié uniquement), auditeur.

Migration : `0007_workforce_management.py` (non destructive). Limites restantes : `docs/limits-and-next-steps.md`.

## Hypothèses non validées (paramétrables)
Les horaires de toutes les marques sont désormais fournis (voir ci-dessus) ; ils restent modifiables (`/shift-templates`, ou `cn_templates` /
`cailler_template` de `build_slots`). Restent des **hypothèses non validées**, signalées dans les alertes, le diagnostic et l'export Excel :
éligibilité marque des collaborateurs sans marque indiquée (Ploom GVA3, GVA9 et Pilar), Pilar sans budget ni besoin hors dimanche,
poids d'attribution (1,25 / 0,75), effectif requis = 1. Lindt et Toblerone : horaires 09–18 enregistrés, mais jours toujours non définis (128 h non planifiables).

## Comptes de démonstration
`python -m app.seed` est **refusé** sauf si `APP_ENV` vaut `development` ou `test` (défaut : `production`) ;
mots de passe jamais codés en dur (`DEMO_PASSWORD` ou génération aléatoire).

## Données manquantes (jamais inventées)
Contrats individuels ; disponibilités complètes ; congés/absences ; qualifications obligatoires ; **jours et horaires
Lindt et Toblerone (128 h)** ; horaires Cailler et Nuxe/Cellcosmet (hypothèses signalées dans le rapport) ;
règles légales applicables et dérogations (validation juridique). Voir `docs/simulation-2026-11.md`.

## Déploiement
Images : `infra/api.Dockerfile`, `infra/web.Dockerfile`. En production : HTTPS obligatoire (`SESSION_COOKIE_SECURE=true`),
secrets via un gestionnaire de secrets, PostgreSQL géré avec sauvegardes, rate-limit partagé (Redis) si plusieurs
instances API, `NEXT_PUBLIC_API_URL` en build-arg, CORS restreint (`CORS_ORIGINS`).

## Limites actuelles et prochaines étapes
Voir `docs/limits-and-next-steps.md`.
