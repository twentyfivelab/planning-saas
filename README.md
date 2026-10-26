# Planning SaaS — planification automatique multi-tenant

Application de planification sous contraintes (OR-Tools CP-SAT) pour entreprises multi-marques / multi-sites.
Fuseau : **Europe/Zurich**. Interface en français (catalogue i18n extensible).

> **Aide à la décision, pas un conseil juridique.** Les valeurs légales (repos 11 h, 6 jours consécutifs) sont des
> références initiales, versionnées et marquées « à valider » : faites-les valider par un spécialiste du droit suisse
> avant toute utilisation en production.

## ⚠️ Statut légal : non commercialisable en l'état
Seules deux règles sont exécutées par le solveur, comme **valeurs de référence non validées juridiquement** :
repos quotidien (défaut 11 h) et maximum de jours consécutifs (défaut 6, règle interne).
**Aucune autre règle légale suisse n'est exécutée** : pauses légales, durée maximale du travail (journalière et
hebdomadaire), travail de nuit, travail du dimanche, jeunes travailleurs, catégories particulières de travailleurs,
dérogations conventionnelles. L'application **ne doit pas être commercialisée ni utilisée en production** pour des
plannings réels tant que ces règles ne sont pas implémentées et validées par un spécialiste du droit suisse.
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
E2E_EMAIL=planner@<domaine> E2E_PASSWORD=<mdp> npx playwright test   # pile Docker lancée
```
Les tests d'intégration exigent PostgreSQL (compose) et migrent via `alembic upgrade head`.
Couverture notable : total 1 752 h ; 90/60/8 shifts ; présence/pause/effectif ; repos 11 h ; 6 jours max ;
Sabrina ; Jane/Chloé ; Ying ≤ 3 j/sem ; verrouillage + réoptimisation partielle ; diagnostic d'infaisabilité ;
Lindt/Toblerone ; aucun contrat inventé ; isolation inter-tenants (API **et** RLS en SQL brut) ; rôles ; CSRF ;
rate-limit ; exports filtrés.
CI : `.github/workflows/ci.yml` (ruff, migrations, pytest, eslint, tsc, vitest, build).

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

## Hypothèses non validées (paramétrables)
Horaires **Cailler** (09:00–18:00) et **Nuxe/Cellcosmet** (08-17, 09-18, 10-19) : non fournis, supposés pour la
simulation. Ce sont des modèles de shifts marqués `is_hypothesis` (modifiables via `/shift-templates`, ou via les
paramètres `cn_templates` / `cailler_template` de `build_slots`), signalés comme **hypothèses non validées** dans les
alertes, le diagnostic et l'export Excel. Idem : éligibilité marque des collaborateurs sans marque indiquée, poids
d'attribution (1,25 / 0,75), effectif requis = 1.

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
