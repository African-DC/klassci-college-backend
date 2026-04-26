#!/usr/bin/env bash
# KLASSCI College — Backup MySQL multi-tenant
#
# Tier 1 (toujours actif) : dump + archive locale dans LOCAL_BACKUP_DIR
#                           rétention par tier (daily/weekly/monthly)
# Tier 2 (opt-in)         : upload vers S3/Spaces si RCLONE_REMOTE configuré
# Tier 3 (opt-in)         : ping healthchecks.io si HEALTHCHECKS_BACKUP_UUID configuré
#
# Tourne quotidien à 02:00 UTC via systemd timer (voir backup-mysql.timer).
# Énumère toutes les DBs tenant (pattern klassci_% + local), dump avec
# consistance InnoDB via docker exec sur le container MySQL.
#
# Variables d'env (charger via /etc/klassci/backup.env) :
#   MYSQL_ROOT_PASSWORD       requis
#   MYSQL_DOCKER_CONTAINER    défaut: klassci-mysql
#   LOCAL_BACKUP_DIR          défaut: /home/ubuntu/klassci/backups
#   LOCAL_RETENTION_DAYS      défaut: 7 (daily; weekly=28, monthly=365 fixes)
#   RCLONE_REMOTE             optionnel — si vide, pas d'upload
#   SPACES_BUCKET             défaut: klassci-backups
#   HEALTHCHECKS_BACKUP_UUID  optionnel — si vide, pas de ping

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
ENV_FILE="${KLASSCI_BACKUP_ENV:-/etc/klassci/backup.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
fi

: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD requis (cf /etc/klassci/backup.env)}"
: "${MYSQL_DOCKER_CONTAINER:=klassci-mysql}"
: "${LOCAL_BACKUP_DIR:=/home/ubuntu/klassci/backups}"
: "${LOCAL_RETENTION_DAYS:=7}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
: "${SPACES_BUCKET:=klassci-backups}"
HEALTHCHECKS_BACKUP_UUID="${HEALTHCHECKS_BACKUP_UUID:-}"

DATE_TAG="$(date -u +%Y%m%d-%H%M%S)"
WORK_DIR="$(mktemp -d -t klassci-backup-XXXXXX)"
ARCHIVE_NAME="klassci-mysql-$DATE_TAG.tar.gz"
ARCHIVE="$WORK_DIR/$ARCHIVE_NAME"
LOG_FILE="$WORK_DIR/backup.log"

cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
ping_healthcheck() {
  # Args: $1=action (start|fail|<empty for success>), $2=optional body
  [[ -z "$HEALTHCHECKS_BACKUP_UUID" ]] && return 0
  local url="https://hc-ping.com/${HEALTHCHECKS_BACKUP_UUID}"
  [[ -n "${1:-}" ]] && url="${url}/${1}"
  if [[ -n "${2:-}" ]]; then
    curl -fsS -m 10 --retry 3 -o /dev/null --data-binary "$2" "$url" || true
  else
    curl -fsS -m 10 --retry 3 -o /dev/null "$url" || true
  fi
}

mysql_exec() {
  # Exécute mysql client dans le container (MYSQL_PWD = mot de passe sans le passer en argv)
  docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_DOCKER_CONTAINER" \
    mysql -uroot "$@"
}

mysqldump_exec() {
  docker exec -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" "$MYSQL_DOCKER_CONTAINER" \
    mysqldump -uroot "$@"
}

# ─────────────────────────────────────────────────────────────────────────────
# Lancement
# ─────────────────────────────────────────────────────────────────────────────
ping_healthcheck start
log "Backup KLASSCI démarré (workdir=$WORK_DIR, container=$MYSQL_DOCKER_CONTAINER)"

# Vérifier que le container tourne
if ! docker inspect -f '{{.State.Running}}' "$MYSQL_DOCKER_CONTAINER" 2>/dev/null | grep -q true; then
  log "ERREUR: container $MYSQL_DOCKER_CONTAINER n'est pas en cours d'exécution"
  ping_healthcheck fail "Container $MYSQL_DOCKER_CONTAINER down"
  exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# 1) Énumérer les DBs tenant : klassci_% + local
# ─────────────────────────────────────────────────────────────────────────────
DBS_QUERY="SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME LIKE 'klassci_%' OR SCHEMA_NAME = 'local';"

DBS=$(mysql_exec --batch --skip-column-names -e "$DBS_QUERY" 2>>"$LOG_FILE")

if [[ -z "${DBS// /}" ]]; then
  log "ERREUR: aucune DB tenant trouvée (pattern klassci_% ou local)"
  ping_healthcheck fail "Aucune DB trouvée"
  exit 1
fi

log "DBs trouvées : $(echo "$DBS" | tr '\n' ' ')"

# ─────────────────────────────────────────────────────────────────────────────
# 2) Dump chaque DB avec consistance InnoDB
# ─────────────────────────────────────────────────────────────────────────────
DUMP_DIR="$WORK_DIR/dumps"
mkdir -p "$DUMP_DIR"

for DB in $DBS; do
  log "Dump $DB..."
  mysqldump_exec \
    --single-transaction \
    --quick \
    --routines \
    --triggers \
    --events \
    --set-gtid-purged=OFF \
    --column-statistics=0 \
    --databases "$DB" \
    > "$DUMP_DIR/$DB.sql" 2>>"$LOG_FILE"

  SIZE=$(stat -c%s "$DUMP_DIR/$DB.sql" 2>/dev/null || stat -f%z "$DUMP_DIR/$DB.sql")
  log "  → $DB.sql (${SIZE} bytes)"
done

# ─────────────────────────────────────────────────────────────────────────────
# 3) Archiver + compresser + tagger metadata
# ─────────────────────────────────────────────────────────────────────────────
cp "$LOG_FILE" "$DUMP_DIR/_backup.log"
echo "$DATE_TAG" > "$DUMP_DIR/_backup.timestamp"
echo "$DBS" | tr '\n' ' ' > "$DUMP_DIR/_backup.databases"

tar -czf "$ARCHIVE" -C "$WORK_DIR" dumps
ARCHIVE_SIZE=$(stat -c%s "$ARCHIVE" 2>/dev/null || stat -f%z "$ARCHIVE")
log "Archive créée: $ARCHIVE_NAME ($ARCHIVE_SIZE bytes)"

# ─────────────────────────────────────────────────────────────────────────────
# 4) Stockage local par tier (daily/weekly/monthly) — TOUJOURS actif
# ─────────────────────────────────────────────────────────────────────────────
DOW=$(date -u +%u)        # 1=Lun .. 7=Dim
DOM=$(date -u +%d)
TIER="daily"
[[ "$DOW" == "7" ]] && TIER="weekly"     # dimanche
[[ "$DOM" == "01" ]] && TIER="monthly"   # 1er du mois (override weekly)

LOCAL_TIER_DIR="$LOCAL_BACKUP_DIR/$TIER"
mkdir -p "$LOCAL_TIER_DIR"
cp "$ARCHIVE" "$LOCAL_TIER_DIR/"
log "Copié dans $LOCAL_TIER_DIR/$ARCHIVE_NAME"

# Rétention locale par tier
case "$TIER" in
  daily)
    find "$LOCAL_TIER_DIR" -name "klassci-mysql-*.tar.gz" -type f \
      -mtime "+${LOCAL_RETENTION_DAYS}" -delete 2>/dev/null || true
    ;;
  weekly)
    find "$LOCAL_TIER_DIR" -name "klassci-mysql-*.tar.gz" -type f \
      -mtime "+28" -delete 2>/dev/null || true
    ;;
  monthly)
    find "$LOCAL_TIER_DIR" -name "klassci-mysql-*.tar.gz" -type f \
      -mtime "+365" -delete 2>/dev/null || true
    ;;
esac

LOCAL_COUNT=$(find "$LOCAL_TIER_DIR" -name "klassci-mysql-*.tar.gz" -type f | wc -l)
log "Rétention $TIER : $LOCAL_COUNT fichier(s) conservé(s) dans $LOCAL_TIER_DIR"

# ─────────────────────────────────────────────────────────────────────────────
# 5) Upload S3/Spaces — opt-in (si RCLONE_REMOTE configuré et rclone installé)
# ─────────────────────────────────────────────────────────────────────────────
if [[ -n "$RCLONE_REMOTE" ]] && command -v rclone >/dev/null 2>&1; then
  if rclone listremotes 2>/dev/null | grep -q "^${RCLONE_REMOTE}:"; then
    REMOTE_PATH="${RCLONE_REMOTE}:${SPACES_BUCKET}/${TIER}/"
    log "Upload vers $REMOTE_PATH..."
    rclone copy "$ARCHIVE" "$REMOTE_PATH" \
      --s3-upload-cutoff 0 \
      --progress=false \
      --stats=0 2>&1 | tee -a "$LOG_FILE"
    log "Upload S3/Spaces terminé"
  else
    log "RCLONE_REMOTE='$RCLONE_REMOTE' non trouvé dans rclone listremotes — skip upload"
  fi
elif [[ -n "$RCLONE_REMOTE" ]]; then
  log "RCLONE_REMOTE configuré mais rclone non installé — skip upload"
else
  log "Mode local-only (RCLONE_REMOTE non configuré) — pas d'upload off-site"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6) Healthchecks.io success ping (avec log en body pour debug) — opt-in
# ─────────────────────────────────────────────────────────────────────────────
ping_healthcheck "" "$(cat "$LOG_FILE")"

log "Backup terminé avec succès"
