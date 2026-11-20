#!/usr/bin/env bash
# Exercice de reprise sur un environnement ISOLÉ et JETABLE, chronométré :
#   1. sauvegarde fraîche de la base (ou fichier .dump donné en argument) ;
#   2. nouveau serveur PostgreSQL dans un conteneur et un réseau dédiés, SANS volume persistant ;
#   3. rôle applicatif, restauration, migrations jusqu'à la version courante ;
#   4. API démarrée sur la base restaurée (port 8200), santé et connexion vérifiées ;
#   5. contrôles : version du schéma, RLS forcée, comptes et empreinte des affectations identiques à la base au moment de la sauvegarde ;
#   6. tout est supprimé à la fin (KEEP=1 pour garder l'environnement et l'examiner).
# La base de l'application et ses volumes ne sont jamais modifiés. Aucune donnée ne quitte la machine.
#   scripts/ops/restore_drill.sh [fichier.dump]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
set -a; source "$ROOT/.env"; set +a
LIVE_PG="${PG_CONTAINER:-planning-postgres-1}"; LIVE_DB="${POSTGRES_DB:-planning}"
NET=planning-restore-net; PGC=planning-restore-pg; APIC=planning-restore-api; PORT=8200; DB=planning
IMG="${API_IMAGE:-planning-api:latest}"
now() { python3 -c 'import time; print(f"{time.time():.3f}")'; }
dur() { python3 -c "print(f'{$2 - $1:.1f} s')"; }
cleanup() { [[ "${KEEP:-}" == 1 ]] && return; docker rm -f "$APIC" "$PGC" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
q() { docker exec "$1" psql -U "$POSTGRES_USER" -d "$2" -Atc "$3"; }
SIG="select (select count(*) from tenants)||' entreprises · '||(select count(*) from employees)||' collaborateurs · '||(select count(*) from planning_periods)||' plannings ('||(select count(*) from planning_periods where deleted_at is not null)||' supprimés, archives : '||(select coalesce(sum(jsonb_array_length(deletion_archive->'assignments')),0) from planning_periods where deletion_archive is not null)||' affectations) · '||(select count(*) from assignments)||' affectations · '||(select count(*) from schedule_versions)||' versions · empreinte '||(select coalesce(md5(string_agg(id::text||employee_id::text||shift_id::text, ',' order by id)),'vide') from assignments)"

T0=$(now)
if [[ $# -ge 1 ]]; then DUMP="$1"; LIVE_SIG="(fichier fourni : comparaison avec la base actuelle non significative)"
else
  OUT="$("$ROOT/scripts/ops/backup.sh")"; echo "$OUT"
  DUMP="$(printf '%s\n' "$OUT" | sed -n 's/^Sauvegarde : \(.*\.dump\).*/\1/p' | head -1)"
  LIVE_SIG="$(q "$LIVE_PG" "$LIVE_DB" "$SIG")"
fi
T1=$(now)
echo "Fichier : $DUMP ($(du -h "$DUMP" | cut -f1))"

docker network create "$NET" >/dev/null
docker run -d --name "$PGC" --network "$NET" -e POSTGRES_USER="$POSTGRES_USER" -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" -e POSTGRES_DB="$DB" postgres:16 >/dev/null
for _ in $(seq 1 60); do docker exec "$PGC" pg_isready -U "$POSTGRES_USER" -d "$DB" >/dev/null 2>&1 && break; sleep 1; done
sleep 2; docker exec "$PGC" pg_isready -U "$POSTGRES_USER" -d "$DB" >/dev/null
T2=$(now)
# rôle applicatif (non superutilisateur, soumis à la RLS), comme la migration initiale ; mot de passe transmis par variable psql
printf '%s\n' "SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS', :'u', :'p') \\gexec" |
  docker exec -i "$PGC" psql -U "$POSTGRES_USER" -d "$DB" -q -v u="$APP_DB_USER" -v p="$APP_DB_PASSWORD" >/dev/null
docker exec -i "$PGC" pg_restore -U "$POSTGRES_USER" -d "$DB" --no-owner --role="$POSTGRES_USER" --exit-on-error < "$DUMP"
T3=$(now)
URL_APP="postgresql+psycopg://$APP_DB_USER:$APP_DB_PASSWORD@$PGC:5432/$DB"; URL_MIG="postgresql+psycopg://$POSTGRES_USER:$POSTGRES_PASSWORD@$PGC:5432/$DB"
docker run --rm --network "$NET" --env-file "$ROOT/.env" -e DATABASE_URL="$URL_APP" -e MIGRATION_DATABASE_URL="$URL_MIG" "$IMG" alembic upgrade head 2>&1 | tail -2
T4=$(now)
docker run -d --name "$APIC" --network "$NET" -p "$PORT:8000" --env-file "$ROOT/.env" -e DATABASE_URL="$URL_APP" -e MIGRATION_DATABASE_URL="$URL_MIG" \
  -e REDIS_URL=redis://indisponible:6379/0 -e RATE_LIMIT_BACKEND=memory "$IMG" uvicorn app.main:app --host 0.0.0.0 --port 8000 >/dev/null
ok=""; for _ in $(seq 1 60); do [[ "$(curl -s -o /dev/null -w '%{http_code}' "localhost:$PORT/health")" == 200 ]] && ok=1 && break; sleep 1; done
[[ -n "$ok" ]] || { echo "API : ÉCHEC (santé)"; docker logs "$APIC" | tail -20; exit 1; }
T5=$(now)

fail=0
check() { if [[ "$2" == "$3" ]]; then echo "  ✔ $1"; else echo "  ✘ $1 : $2 (attendu $3)"; fail=1; fi; }
echo "Contrôles :"
check "version du schéma = version de l'application ($(q "$PGC" "$DB" "select version_num from alembic_version"))" \
  "$(q "$PGC" "$DB" "select version_num from alembic_version")" "$(docker run --rm "$IMG" alembic heads 2>/dev/null | awk '{print $1}' | head -1)"
check "RLS forcée sur toutes les tables de l'entreprise" "$(q "$PGC" "$DB" "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r' and c.relname <> 'sessions' and exists (select 1 from information_schema.columns i where i.table_name=c.relname and i.column_name='tenant_id') and not (c.relrowsecurity and c.relforcerowsecurity)")" "0"
check "rôle applicatif soumis à la RLS" "$(q "$PGC" "$DB" "select rolbypassrls from pg_roles where rolname='$APP_DB_USER'")" "f"
RESTORED_SIG="$(q "$PGC" "$DB" "$SIG")"
echo "  · base au moment de la sauvegarde : $LIVE_SIG"
echo "  · base restaurée                  : $RESTORED_SIG"
[[ $# -ge 1 ]] || check "données restaurées identiques (plannings, archives, affectations, versions, empreinte)" "$RESTORED_SIG" "$LIVE_SIG"
# connexion réelle : compte TEMPORAIRE (mot de passe aléatoire) créé uniquement dans l'environnement restauré, détruit avec lui
TMP_PW="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
TENANT="$(q "$PGC" "$DB" "select tenant_id from users where email='owner@rules.example'")"
if [[ -n "$TENANT" ]]; then
  docker exec -e TMP_PW="$TMP_PW" -e TENANT="$TENANT" "$APIC" python -c '
import os, uuid
from app.db import tenant_session
from app import models as m
from app.security import hash_password
with tenant_session(os.environ["TENANT"]) as db:
    db.add(m.User(tenant_id=uuid.UUID(os.environ["TENANT"]), email="reprise@restore.example", name="Contrôle de reprise", password_hash=hash_password(os.environ["TMP_PW"]), role="auditor"))'
  JAR="$(mktemp)"
  code=$(curl -s -c "$JAR" -o /dev/null -w '%{http_code}' -H 'content-type: application/json' -d "{\"email\":\"reprise@restore.example\",\"password\":\"$TMP_PW\"}" "localhost:$PORT/auth/login")
  check "connexion à l'application restaurée (compte temporaire, lecture seule)" "$code" "200"
  n_api=$(curl -s -b "$JAR" "localhost:$PORT/periods" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
  n_sql=$(q "$PGC" "$DB" "select count(*) from planning_periods where tenant_id='$TENANT' and deleted_at is null")
  check "plannings lus par l'API restaurée = base restaurée ($n_api)" "$n_api" "$n_sql"
  rm -f "$JAR"
fi
T6=$(now)
echo "Durées : sauvegarde $(dur "$T0" "$T1") · serveur neuf $(dur "$T1" "$T2") · restauration $(dur "$T2" "$T3") · migrations $(dur "$T3" "$T4") · API prête $(dur "$T4" "$T5") · contrôles $(dur "$T5" "$T6") · TOTAL $(dur "$T0" "$T6")"
[[ $fail == 0 ]] && echo "Exercice de reprise : RÉUSSI" || { echo "Exercice de reprise : ÉCHEC"; exit 1; }
