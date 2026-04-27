#!/usr/bin/env bash
# KLASSCI College — Test de restauration des backups
#
# Récupère le dernier backup (local en priorité, S3/Spaces en fallback),
# le restaure dans des DBs temporaires préfixées, vérifie l'intégrité
# (nombre de tables + counts sur tables critiques), drop les DBs temp.
#
# Tourne hebdomadaire le dimanche 03:00 UTC via systemd timer.
#
# Variables d'env (cf /etc/klassci/backup.env) :
#   MYSQL_ROOT_PASSWORD       requis
#   MYSQL_DOCKER_CONTAINER    défaut: klassci-mysql
#   LOCAL_BACKUP_DIR          défaut: /home/ubuntu/klassci/backups
#   RCLONE_REMOTE             optionnel — si vide ou local existe, on utilise local
#   SPACES_BUCKET             défaut: klassci-backups
#   HEALTHCHECKS_RESTORE_UUID optionnel — si vide, pas de ping

set -euo pipefail

ENV_FILE="${KLASSCI_BACKUP_ENV:-/etc/klassci/backup.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD requis}"
: "${MYSQL_DOCKER_CONTAINER:=klassci-mysql}"
: "${LOCAL_BACKUP_DIR:=/home/ubuntu/klassci/backups}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
: "${SPACES_BUCKET:=klassci-backups}"
HEALTHCHECKS_RESTORE_UUID="${HEALTHCHECKS_RESTORE_UUID:-}"

DATE_TAG="$(date -u +%Y%m%d-%H%M%S)"
WORK_DIR="$(mktemp -d -t klassci-restore-test-XXXXXX)"
LOG_FILE="$WORK_DIR/restore.log"
TEMP_PREFIX="restore_test_${DATE_TAG}"
TEMP_DBS=""

cleanup() {
  if [[ -n "$TEMP_DBS" ]]; then
    for DB in $TEMP_DBS; do
      docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_DOCKER_CONTAINER" \
        mysql -uroot -e "DROP DATABASE IF EXISTS \`${DB}\`" 2>/dev/null || true
    done
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

ping_healthcheck() {
  [[ -z "$HEALTHCHECKS_RESTORE_UUID" ]] && return 0
  local url="https://hc-ping.com/${HEALTHCHECKS_RESTORE_UUID}"
  [[ -n "${1:-}" ]] && url="${url}/${1}"
  if [[ -n "${2:-}" ]]; then
    curl -fsS -m 10 --retry 3 -o /dev/null --data-binary "$2" "$url" || true
  else
    curl -fsS -m 10 --retry 3 -o /dev/null "$url" || true
  fi
}

mysql_exec() {
  docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_DOCKER_CONTAINER" \
    mysql -uroot "$@"
}

ping_healthcheck start
log "Restore-test démarré (workdir=$WORK_DIR)"

# ─────────────────────────────────────────────────────────────────────────────
# 1) Trouver le backup le plus récent (local prioritaire)
# ─────────────────────────────────────────────────────────────────────────────
LATEST_LOCAL=""
for TIER in daily weekly monthly; do
  if [[ -d "$LOCAL_BACKUP_DIR/$TIER" ]]; then
    CANDIDATE=$(find "$LOCAL_BACKUP_DIR/$TIER" -name "klassci-mysql-*.tar.gz" -type f \
      -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2- || true)
    if [[ -n "$CANDIDATE" ]]; then
      if [[ -z "$LATEST_LOCAL" ]] || [[ "$CANDIDATE" -nt "$LATEST_LOCAL" ]]; then
        LATEST_LOCAL="$CANDIDATE"
      fi
    fi
  fi
done

ARCHIVE_PATH=""
if [[ -n "$LATEST_LOCAL" ]]; then
  ARCHIVE_PATH="$LATEST_LOCAL"
  log "Backup local trouvé : $ARCHIVE_PATH"
elif [[ -n "$RCLONE_REMOTE" ]] && command -v rclone >/dev/null 2>&1; then
  log "Pas de backup local, recherche dans S3/Spaces..."
  LATEST=$(rclone lsf "${RCLONE_REMOTE}:${SPACES_BUCKET}/daily/" \
    --include "klassci-mysql-*.tar.gz" 2>/dev/null | sort | tail -1)
  if [[ -z "$LATEST" ]]; then
    log "ERREUR: aucun backup trouvé (ni local, ni dans daily/)"
    ping_healthcheck fail "Aucun backup disponible"
    exit 1
  fi
  rclone copy "${RCLONE_REMOTE}:${SPACES_BUCKET}/daily/${LATEST}" "$WORK_DIR/" \
    --progress=false 2>&1 | tee -a "$LOG_FILE"
  ARCHIVE_PATH="$WORK_DIR/$LATEST"
  log "Backup S3 récupéré : $LATEST"
else
  log "ERREUR: aucun backup local et pas de RCLONE_REMOTE configuré"
  ping_healthcheck fail "Aucun backup disponible"
  exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# 2) Extract
# ─────────────────────────────────────────────────────────────────────────────
tar -xzf "$ARCHIVE_PATH" -C "$WORK_DIR"
log "Backup extrait dans $WORK_DIR/dumps"

# ─────────────────────────────────────────────────────────────────────────────
# 3) Restore chaque DB dans une DB temp préfixée
# ─────────────────────────────────────────────────────────────────────────────
ERRORS=0

for SQL_FILE in "$WORK_DIR"/dumps/*.sql; do
  [[ -e "$SQL_FILE" ]] || continue

  ORIGINAL_DB=$(basename "$SQL_FILE" .sql)
  TEMP_DB="${TEMP_PREFIX}_${ORIGINAL_DB}"
  TEMP_DBS="$TEMP_DBS $TEMP_DB"

  log "Restore $ORIGINAL_DB → $TEMP_DB..."

  # Réécrire CREATE/USE pour pointer vers la temp DB, puis pipe dans mysql client
  sed -e "s/CREATE DATABASE.*\`${ORIGINAL_DB}\`/CREATE DATABASE IF NOT EXISTS \`${TEMP_DB}\`/g" \
      -e "s/USE \`${ORIGINAL_DB}\`/USE \`${TEMP_DB}\`/g" \
      "$SQL_FILE" \
    | docker exec -i -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_DOCKER_CONTAINER" \
        mysql -uroot 2>>"$LOG_FILE"

  # Vérification : compter les tables et estimer la santé
  TABLE_COUNT=$(mysql_exec -D "$TEMP_DB" --batch --skip-column-names \
    -e "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = '$TEMP_DB';" 2>/dev/null \
    | head -1 || echo "0")

  if [[ "$TABLE_COUNT" -lt 5 ]]; then
    log "  ✗ $TEMP_DB : seulement $TABLE_COUNT tables (suspect, attendu >=5)"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  # Counts supplémentaires sur tables critiques (peuvent être 0 sur tenant neuf)
  USERS_COUNT=$(mysql_exec -D "$TEMP_DB" --batch --skip-column-names \
    -e "SELECT COUNT(*) FROM users;" 2>/dev/null | head -1 || echo "n/a")
  STUDENTS_COUNT=$(mysql_exec -D "$TEMP_DB" --batch --skip-column-names \
    -e "SELECT COUNT(*) FROM students;" 2>/dev/null | head -1 || echo "n/a")

  log "  ✓ $TEMP_DB : ${TABLE_COUNT} tables, users=${USERS_COUNT}, students=${STUDENTS_COUNT}"
done

# ─────────────────────────────────────────────────────────────────────────────
# 4) Verdict
# ─────────────────────────────────────────────────────────────────────────────
if [[ $ERRORS -gt 0 ]]; then
  log "ÉCHEC: $ERRORS erreur(s) de restauration"
  ping_healthcheck fail "$(cat "$LOG_FILE")"
  exit 1
fi

log "Restore-test réussi pour toutes les DBs"
ping_healthcheck "" "$(cat "$LOG_FILE")"
