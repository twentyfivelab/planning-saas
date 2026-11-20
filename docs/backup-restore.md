# Sauvegarde et restauration

**Sauvegarde logique quotidienne** (rôle propriétaire, pas le rôle applicatif) :
```bash
docker compose -f infra/compose.yaml --env-file .env exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" > backup-$(date +%F).dump
```
Chiffrer l'archive au repos (ex. `age`/KMS), la copier hors site, conserver selon `docs/retention.md`.

**Restauration** (sur une base vide, puis vérifier) :
```bash
docker compose -f infra/compose.yaml --env-file .env exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < backup.dump
docker compose -f infra/compose.yaml --env-file .env exec api alembic current
```
Les politiques RLS, rôles et fonctions sont inclus dans le dump ; le rôle `planning_app` doit exister (migration).
Tester la restauration au moins trimestriellement. En production : PITR/WAL archiving géré par l'hébergeur.

## Exercice de reprise chronométré (environnement isolé et jetable)

```
scripts/ops/restore_drill.sh            # sauvegarde fraîche puis reprise complète
scripts/ops/restore_drill.sh fichier.dump
```

Étapes, toutes chronométrées :
1. sauvegarde (`backup.sh`) ;
2. nouveau serveur PostgreSQL dans un conteneur et un réseau dédiés, sans volume persistant ;
3. rôle applicatif soumis à la RLS, restauration (`pg_restore --exit-on-error`), migrations jusqu'à la version de l'application ;
4. API démarrée sur la base restaurée (port 8200), santé vérifiée ;
5. connexion réelle avec un compte temporaire créé **uniquement** dans l'environnement restauré (lecture seule, détruit avec lui) ; plannings lus par l'API égaux à la base ;
6. contrôles : version du schéma, RLS forcée, rôle sans contournement de la RLS ; comptes et empreinte des affectations identiques à la base au moment de la sauvegarde.

Tout est supprimé à la fin (`KEEP=1` pour garder l'environnement). La base de l'application et ses volumes ne sont jamais modifiés, et aucune donnée ne quitte la machine.

**Résultat du 20/11/2026** (base locale : 107 entreprises, 454 collaborateurs, 48 plannings dont 7 supprimés avec 1 175 affectations archivées, 4 854 affectations, 96 versions) — réussi, données identiques :

| Étape | Durée |
|---|---|
| Sauvegarde | 1,0 s |
| Serveur neuf | 4,0 s |
| Restauration | 0,8 s |
| Migrations | 0,9 s |
| API prête | 2,5 s |
| Contrôles | 1,4 s |
| **Total** | **10,6 s** |

Limite : base de petite taille (2,7 Mo compressés) ; la durée de restauration croît avec le volume et doit être remesurée sur l'environnement de production choisi (décision D1).
