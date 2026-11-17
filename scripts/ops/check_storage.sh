#!/usr/bin/env bash
# Alerte avant saturation du stockage : espace libre, Docker (cache récupérable), sauvegardes. Code 1 sous le seuil.
# MIN_FREE_GB (défaut 20). Ne supprime rien : affiche les commandes sûres (cache de construction, images orphelines ; jamais les volumes).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MIN="${MIN_FREE_GB:-20}"
FREE=$(df -g "$ROOT" | awk 'NR==2 {print $4}')
echo "Espace libre : ${FREE} Go (seuil ${MIN} Go)"
docker system df 2>/dev/null | sed -n '1,5p'
echo "Sauvegardes : $(du -sh "$ROOT/backups" 2>/dev/null | cut -f1) ($(ls "$ROOT"/backups/*.dump 2>/dev/null | wc -l | tr -d ' ') fichiers)"
if (( FREE < MIN )); then
  echo "ALERTE : moins de ${MIN} Go libres. Libération sans risque pour les données : docker builder prune -f ; docker image prune -f"
  exit 1
fi
