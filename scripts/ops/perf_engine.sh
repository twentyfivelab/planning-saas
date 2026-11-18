#!/usr/bin/env bash
# Mesures de performance du moteur (tests marqués « perf »), séparées des tests de correction.
# Les conditions sont consignées avec le résultat dans docs/mesures-moteur.md : date, commit, processeur, cœurs, mémoire,
# charge avant la mesure, versions. Une machine trop chargée n'est pas « corrigée » par un délai plus long : la mesure est refusée
# (ou, avec PERF_FORCE=1, consignée comme « conditions non conformes »).
set -euo pipefail
cd "$(dirname "$0")/../.."
PY=${PY:-.venv/bin/python}
OUT=docs/mesures-moteur.md
cores=$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu)
load=$(uptime | sed -E 's/.*load averages?: *([0-9.,]+).*/\1/' | tr -d ',' | cut -d' ' -f1)
limit=$(awk -v c="$cores" 'BEGIN{print c*0.25}')
ok=$(awk -v l="$load" -v m="$limit" 'BEGIN{print (l<=m)?"oui":"non"}')
if [ "$ok" = "non" ] && [ "${PERF_FORCE:-0}" != "1" ]; then
  echo "Charge actuelle $load > $limit (25 % de $cores cœurs) : mesure refusée. Attendez une machine disponible ou PERF_FORCE=1." >&2
  exit 2
fi
cpu=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || grep -m1 "model name" /proc/cpuinfo | cut -d: -f2 | xargs)
mem=$(( $(sysctl -n hw.memsize 2>/dev/null || awk '/MemTotal/{print $2*1024}' /proc/meminfo) / 1073741824 ))
commit=$(git rev-parse --short HEAD)$(git diff --quiet HEAD -- packages/solver || echo "+modifs")
ortools=$($PY -c "import ortools; print(ortools.__version__)")
pyv=$($PY -c "import platform; print(platform.python_version())")
log=$(mktemp)
set +e
(cd packages/solver && "../../$PY" -m pytest -m perf -q -p no:warnings --durations=0 -rA) >"$log" 2>&1
rc=$?
set -e
cat "$log"
res=$(grep -E "passed|failed" "$log" | tail -1 | sed -E 's/=+//g' | xargs)
durs=$(grep -E "^[0-9.]+s call" "$log" | sed -E 's/^([0-9.]+)s call +[^:]+::([a-z_]+).*/\2 \1 s/' | paste -sd ';' - | sed 's/;/ ; /g')
timing=$(grep -m1 -E "^TIMING " "$log" | sed -E 's/^TIMING //; s/model_s=/modèle /; s/ search_s=/ s, recherche /; s/ post_s=/ s, contrôles /; s/ engine_total_s=/ s, total moteur /; s/ time_limit_s=/ s (durée maximale /; s/$/ s)/')
[ -n "$timing" ] && durs="$durs — $timing"
[ -f "$OUT" ] || printf '# Mesures de performance du moteur\n\nProduites par `scripts/ops/perf_engine.sh` (tests marqués « perf »). Les tests de correction, eux, ne dépendent pas de la charge de la machine (vérifié sous charge : voir `docs/suivi-wfm.md`).\n\n| Date | Commit | Machine | Charge avant | Conditions | Versions | Résultat | Durées |\n|---|---|---|---|---|---|---|---|\n' >"$OUT"
cond=$([ "$ok" = "oui" ] && echo "conformes" || echo "**non conformes (forcé)**")
echo "| $(date '+%d/%m/%Y %H:%M') | $commit | $cpu, $cores cœurs, $mem Go | $load | $cond | Python $pyv, OR-Tools $ortools | $res | $durs |" >>"$OUT"
rm -f "$log"
echo "Consigné dans $OUT"
exit $rc
