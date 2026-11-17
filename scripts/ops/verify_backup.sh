#!/usr/bin/env bash
# Vérifie qu'une sauvegarde se RESTAURE réellement, dans une base isolée (planning_restore_check), puis la supprime.
# Usage : scripts/ops/verify_backup.sh [fichier.dump]   (par défaut : la plus récente de backups/)   KEEP=1 pour garder la base.
# La base de l'application n'est jamais modifiée. Code de sortie non nul si la restauration ou un contrôle échoue.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
set -a; source "$ROOT/.env"; set +a
PG="${PG_CONTAINER:-planning-postgres-1}"; LIVE="${POSTGRES_DB:-planning}"; CHK="planning_restore_check"
DUMP="${1:-$(ls -1t "$ROOT"/backups/*.dump | head -1)}"
q() { docker exec "$PG" psql -U "$POSTGRES_USER" -d "$1" -Atc "$2"; }
echo "Sauvegarde : $DUMP"
q postgres "DROP DATABASE IF EXISTS $CHK WITH (FORCE)" >/dev/null
q postgres "CREATE DATABASE $CHK" >/dev/null
trap '[[ "${KEEP:-}" == 1 ]] || q postgres "DROP DATABASE IF EXISTS '$CHK' WITH (FORCE)" >/dev/null' EXIT
docker exec -i "$PG" pg_restore -U "$POSTGRES_USER" -d "$CHK" --no-owner --role="$POSTGRES_USER" --exit-on-error < "$DUMP"
echo "Restauration : OK"
fail=0
check() { if [[ "$2" == "$3" ]]; then echo "  ✔ $1 : $2"; else echo "  ✘ $1 : $2 (attendu $3)"; fail=1; fi; }
check "version du schéma présente" "$(q $CHK "select count(*) from alembic_version")" "1"
echo "  · version du schéma : $(q $CHK "select version_num from alembic_version")"
# « sessions » est globale par conception (recherche par empreinte du jeton, avant de connaître le tenant) : seule exception admise
check "tables du tenant sans RLS forcée" "$(q $CHK "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r' and c.relname <> 'sessions' and exists (select 1 from information_schema.columns i where i.table_name=c.relname and i.column_name='tenant_id') and not (c.relrowsecurity and c.relforcerowsecurity)")" "0"
check "rôle applicatif présent" "$(q $CHK "select count(*) from pg_roles where rolname='${APP_DB_USER:-planning_app}'")" "1"
echo "  · tenants : $(q $CHK "select count(*) from tenants") ; collaborateurs : $(q $CHK "select count(*) from employees") ; affectations : $(q $CHK "select count(*) from assignments")"
FP="select coalesce(md5(string_agg(p.name||'|'||s.slot_key||'|'||a.employee_id, ',' order by p.name, s.slot_key)),'vide') from assignments a join shifts s on s.id=a.shift_id join planning_periods p on p.id=a.period_id where a.tenant_id=(select tenant_id from users where email='owner@rules.example')"
B="$(q $CHK "$FP")"; L="$(q "$LIVE" "$FP")"
echo "  · empreinte des plannings de la démo : sauvegarde $B / base actuelle $L $([[ "$B" == "$L" ]] && echo '(identiques)' || echo '(différentes : la base a évolué depuis la sauvegarde)')"
[[ $fail == 0 ]] && echo "Vérification : OK" || { echo "Vérification : ÉCHEC"; exit 1; }
