#!/usr/bin/env bash
# Tests navigateur sur une pile ISOLÉE (infra/compose.e2e.yaml : base planning_e2e, ports 3100 / 8100), jamais sur la base de développement.
#   scripts/ops/e2e_stack.sh up      construit et démarre la pile, crée le tenant de test (une seule fois) et génère novembre 2026
#   scripts/ops/e2e_stack.sh test    lance la suite Playwright sur cette pile (arguments supplémentaires transmis à Playwright)
#   scripts/ops/e2e_stack.sh down    arrête la pile ; DATA=drop supprime aussi SA base de test (volume planning-e2e_pgdata_e2e uniquement)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
C=(docker compose --env-file "$ROOT/.env" -f "$ROOT/infra/compose.e2e.yaml")
PWFILE="$ROOT/apps/web/e2e/.auth/e2e-isolated-password.txt"
API=http://localhost:8100

wait_http() { for _ in $(seq 1 90); do [[ "$(curl -s -o /dev/null -w '%{http_code}' "$1")" == 200 ]] && return 0; sleep 2; done; echo "Délai dépassé : $1"; return 1; }

case "${1:-}" in
  up)
    "${C[@]}" up -d --build
    wait_http "$API/health"
    if [[ ! -s "$PWFILE" ]]; then
      mkdir -p "$(dirname "$PWFILE")"
      OUT="$("${C[@]}" exec -T api python -c "from app.seed import seed; import json; print(json.dumps(seed(tenant_name='Tests automatiques e2e', domain='e2e.example')))" | tail -1)"
      PW="$(printf '%s' "$OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['password'])")"
      if [[ "$PW" == "(DEMO_PASSWORD)" ]]; then PW="$(grep '^DEMO_PASSWORD=' "$ROOT/.env" | cut -d= -f2-)"; fi
      (umask 077; printf '%s' "$PW" > "$PWFILE")
      JAR="$ROOT/apps/web/e2e/.auth/e2e-isolated-cookies.txt"
      CSRF=$(curl -s -c "$JAR" -H 'content-type: application/json' -d "{\"email\":\"owner@e2e.example\",\"password\":\"$PW\"}" "$API/auth/login" | python3 -c "import json,sys; print(json.load(sys.stdin)['csrf_token'])")
      PID=$(curl -s -b "$JAR" -H "x-csrf-token: $CSRF" -H 'content-type: application/json' -d '{"year":2026,"month":11}' "$API/periods/ensure" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
      curl -s -b "$JAR" -H "x-csrf-token: $CSRF" -H "Idempotency-Key: e2e-init-$PID" -H 'content-type: application/json' -d '{"time_limit_s":30}' "$API/periods/$PID/runs" > /dev/null
      echo "Tenant de test créé dans la base isolée ; génération de novembre 2026 lancée."
    fi
    wait_http http://localhost:3100/login
    echo "Pile e2e prête : http://localhost:3100 (API $API)";;
  test)
    shift
    cd "$ROOT/apps/web"
    E2E_EMAIL=owner@e2e.example E2E_PASSWORD="$(cat "$PWFILE")" WEB_URL=http://localhost:3100 API_URL="$API" \
      E2E_DB_CONTAINER=planning-e2e-postgres-1 POSTGRES_DB=planning_e2e npx playwright test "$@";;
  down)
    if [[ "${DATA:-}" == drop ]]; then "${C[@]}" down -v && : > "$PWFILE"; else "${C[@]}" down; fi;;
  *) echo "usage : $0 up|test|down"; exit 2;;
esac
