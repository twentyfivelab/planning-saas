#!/usr/bin/env bash
# Sauvegarde logique de la base (rôle propriétaire) dans backups/auto-AAAAMMJJ-HHMMSS.dump, lisibilité vérifiée.
# Rétention : AUCUNE suppression par défaut. KEEP_AUTO=N conserve les N dernières sauvegardes « auto-* » (jamais les sauvegardes nommées).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
set -a; source "$ROOT/.env"; set +a
PG="${PG_CONTAINER:-planning-postgres-1}"; DB="${POSTGRES_DB:-planning}"
mkdir -p "$ROOT/backups"; chmod 700 "$ROOT/backups"
OUT="$ROOT/backups/${1:-auto-$(date +%Y%m%d-%H%M%S)}.dump"
docker exec "$PG" pg_dump -U "$POSTGRES_USER" -d "$DB" -Fc > "$OUT.tmp"
docker exec -i "$PG" pg_restore --list < "$OUT.tmp" > /dev/null   # archive lisible, sinon échec
mv "$OUT.tmp" "$OUT"; chmod 600 "$OUT"
echo "Sauvegarde : $OUT ($(du -h "$OUT" | cut -f1))"
if [[ -n "${KEEP_AUTO:-}" ]]; then
  ls -1t "$ROOT"/backups/auto-*.dump 2>/dev/null | tail -n +"$((KEEP_AUTO + 1))" | while read -r old; do echo "Rétention : $old"; rm -f "$old"; done
fi
