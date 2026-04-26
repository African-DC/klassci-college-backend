#!/usr/bin/env bash
# KLASSCI College — Test de restauration backup
#
# Pull le dernier backup depuis Spaces, restore dans une DB temp,
# vérifie que les tables principales contiennent des données, drop la DB temp.
# Pingue healthchecks.io séparé (différent du UUID du backup quotidien).
#
# Tourne hebdo le dimanche 03:00 UTC via systemd timer (restore-test.timer).
#
# Variables d'env requises (charger via /etc/klassci/backup.env) :
#   MYSQL_HOST, MYSQL_PORT, MYSQL_ROOT_USER, MYSQL_ROOT_PASSWORD
#   RCLONE_REMOTE, SPACES_BUCKET
#   HEALTHCHECKS_RESTORE_UUID

set -euo pipefail

ENV_FILE="${KLASSCI_BACKUP_ENV:-/etc/klassci/backup.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

: "${MYSQL_HOST:=127.0.0.1}"
: "${MYSQL_PORT:=3306}"
: "${MYSQL_ROOT_USER:=root}"
: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD requis}"
: "${RCLONE_REMOTE:=do-spaces}"
: "${SPACES_BUCKET:=klassci-backups}"
: "${HEALTHCHECKS_RESTORE_UUID:?HEALTHCHECKS_RESTORE_UUID requis}"

DATE_TAG="$(date -u +%Y%m%d-%H%M%S)"
WORK_DIR="$(mktemp -d -t klassci-restore-test-XXXXXX)"
LOG_FILE="$WORK_DIR/restore.log"
TEMP_PREFIX="restore_test_${DATE_TAG}"

cleanup() {
  # Drop des DBs temp même si script crash
  if [[ -n "${TEMP_DBS:-}" ]]; then
    for DB in $TEMP_DBS; do
      mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" \
        -u "$MYSQL_ROOT_USER" -p"$MYSQL_ROOT_PASSWORD" \
        -e "DROP DATABASE IF EXISTS \`${DB}\`" 2>/dev/null || true
    done
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

curl -fsS -m 10 --retry 3 -o /dev/null \
  "https://hc-ping.com/${HEALTHCHECKS_RESTORE_UUID}/start" || true

log "Restore-test démarré — workdir=$WORK_DIR"

# ─────────────────────────────────────────────────────────────────────────────
# 1) Trouver le backup le plus récent dans daily/
# ─────────────────────────────────────────────────────────────────────────────
LATEST=$(rclone lsf "${RCLONE_REMOTE}:${SPACES_BUCKET}/daily/" \
  --include "klassci-mysql-*.tar.gz" 2>/dev/null \
  | sort | tail -1)

if [[ -z "$LATEST" ]]; then
  log "ERREUR: aucun backup trouvé dans daily/"
  curl -fsS -m 10 -o /dev/null \
    "https://hc-ping.com/${HEALTHCHECKS_RESTORE_UUID}/fail" \
    --data-binary "Aucun backup trouvé"
  exit 1
fi

log "Backup à tester: $LATEST"

# ─────────────────────────────────────────────────────────────────────────────
# 2) Pull + extract
# ─────────────────────────────────────────────────────────────────────────────
rclone copy "${RCLONE_REMOTE}:${SPACES_BUCKET}/daily/${LATEST}" "$WORK_DIR/" \
  --progress=false 2>&1 | tee -a "$LOG_FILE"

tar -xzf "$WORK_DIR/$LATEST" -C "$WORK_DIR"
log "Backup extrait dans $WORK_DIR/dumps"

# ─────────────────────────────────────────────────────────────────────────────
# 3) Restore chaque DB dans une DB temp préfixée
# ─────────────────────────────────────────────────────────────────────────────
TEMP_DBS=""
ERRORS=0

for SQL_FILE in "$WORK_DIR"/dumps/*.sql; do
  [[ -e "$SQL_FILE" ]] || continue

  ORIGINAL_DB=$(basename "$SQL_FILE" .sql)
  TEMP_DB="${TEMP_PREFIX}_${ORIGINAL_DB}"
  TEMP_DBS="$TEMP_DBS $TEMP_DB"

  log "Restore $ORIGINAL_DB → $TEMP_DB..."

  # Réécrire les CREATE/USE pour pointer vers la temp DB
  # (mysqldump --databases injecte CREATE DATABASE + USE)
  sed -e "s/CREATE DATABASE.*\`${ORIGINAL_DB}\`/CREATE DATABASE IF NOT EXISTS \`${TEMP_DB}\`/g" \
      -e "s/USE \`${ORIGINAL_DB}\`/USE \`${TEMP_DB}\`/g" \
      "$SQL_FILE" \
    | mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" \
        -u "$MYSQL_ROOT_USER" -p"$MYSQL_ROOT_PASSWORD" 2>>"$LOG_FILE"

  # Vérification : compter les rows sur les tables critiques
  COUNT_QUERY="SELECT
      (SELECT COUNT(*) FROM users) AS users_count,
      (SELECT COUNT(*) FROM students) AS students_count,
      (SELECT COUNT(*) FROM enrollments) AS enrollments_count;"

  COUNTS=$(mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" \
    -u "$MYSQL_ROOT_USER" -p"$MYSQL_ROOT_PASSWORD" \
    -D "$TEMP_DB" --batch --skip-column-names -e "$COUNT_QUERY" 2>/dev/null \
    | head -1 || echo "ERROR")

  if [[ "$COUNTS" == "ERROR" ]]; then
    log "  ✗ $TEMP_DB : impossible de compter (tables manquantes?)"
    ERRORS=$((ERRORS + 1))
  else
    log "  ✓ $TEMP_DB : counts=$COUNTS"
  fi
done

# ─────────────────────────────────────────────────────────────────────────────
# 4) Verdict
# ─────────────────────────────────────────────────────────────────────────────
if [[ $ERRORS -gt 0 ]]; then
  log "ÉCHEC: $ERRORS erreur(s) de restauration"
  curl -fsS -m 10 -o /dev/null \
    "https://hc-ping.com/${HEALTHCHECKS_RESTORE_UUID}/fail" \
    --data-binary "@$LOG_FILE"
  exit 1
fi

log "Restore-test réussi pour toutes les DBs"
curl -fsS -m 10 --retry 3 -o /dev/null \
  --data-binary "@$LOG_FILE" \
  "https://hc-ping.com/${HEALTHCHECKS_RESTORE_UUID}"
