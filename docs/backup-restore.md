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
