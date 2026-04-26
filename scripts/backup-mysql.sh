#!/usr/bin/env bash
# KLASSCI College — Backup MySQL multi-tenant vers DigitalOcean Spaces (ou S3)
#
# Tourne quotidien à 02:00 UTC via systemd timer (voir backup-mysql.timer).
# Enumère toutes les DBs tenant (pattern klassci_% + local), dump avec
# consistance InnoDB, compresse, upload vers Spaces, ping healthchecks.io.
#
# Variables d'env requises (charger via /etc/klassci/backup.env) :
#   MYSQL_HOST, MYSQL_PORT, MYSQL_ROOT_USER, MYSQL_ROOT_PASSWORD
#   RCLONE_REMOTE        (ex: do-spaces)
#   SPACES_BUCKET        (ex: klassci-backups)
#   HEALTHCHECKS_BACKUP_UUID  (UUID healthchecks.io)
#
# Pré-requis sur le host :
#   apt install mysql-client rclone curl
#   rclone config (remote DigitalOcean Spaces ou S3)

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
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
: "${HEALTHCHECKS_BACKUP_UUID:?HEALTHCHECKS_BACKUP_UUID requis}"

DATE_TAG="$(date -u +%Y%m%d-%H%M%S)"
WORK_DIR="$(mktemp -d -t klassci-backup-XXXXXX)"
ARCHIVE="$WORK_DIR/klassci-mysql-$DATE_TAG.tar.gz"
LOG_FILE="$WORK_DIR/backup.log"

cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

# ─────────────────────────────────────────────────────────────────────────────
# Healthchecks.io start ping (signale le démarrage, pas obligatoire)
# ─────────────────────────────────────────────────────────────────────────────
curl -fsS -m 10 --retry 3 -o /dev/null \
  "https://hc-ping.com/${HEALTHCHECKS_BACKUP_UUID}/start" || true

log "Backup KLASSCI démarré — workdir=$WORK_DIR"

# ─────────────────────────────────────────────────────────────────────────────
# 1) Enumérer les DBs tenant : klassci_% + local
# ─────────────────────────────────────────────────────────────────────────────
DBS_QUERY="SELECT SCHEMA_NAME FROM information_schema.SCHEMATA
           WHERE SCHEMA_NAME LIKE 'klassci_%' OR SCHEMA_NAME = 'local';"

DBS=$(mysql \
  -h "$MYSQL_HOST" -P "$MYSQL_PORT" \
  -u "$MYSQL_ROOT_USER" -p"$MYSQL_ROOT_PASSWORD" \
  --batch --skip-column-names -e "$DBS_QUERY")

if [[ -z "${DBS// /}" ]]; then
  log "ERREUR: aucune DB tenant trouvée (pattern klassci_% ou local)"
  curl -fsS -m 10 --retry 3 -o /dev/null \
    "https://hc-ping.com/${HEALTHCHECKS_BACKUP_UUID}/fail" \
    --data-binary "Aucune DB trouvée"
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
  mysqldump \
    -h "$MYSQL_HOST" -P "$MYSQL_PORT" \
    -u "$MYSQL_ROOT_USER" -p"$MYSQL_ROOT_PASSWORD" \
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
log "Archive créée: $ARCHIVE ($(stat -c%s "$ARCHIVE" 2>/dev/null || stat -f%z "$ARCHIVE") bytes)"

# ─────────────────────────────────────────────────────────────────────────────
# 4) Upload vers Spaces avec dossier tagué (daily/weekly/monthly)
# ─────────────────────────────────────────────────────────────────────────────
DOW=$(date -u +%u)        # 1=Lun .. 7=Dim
DOM=$(date -u +%d)
TIER="daily"
[[ "$DOW" == "7" ]] && TIER="weekly"     # dimanche
[[ "$DOM" == "01" ]] && TIER="monthly"   # 1er du mois (override weekly)

REMOTE_PATH="${RCLONE_REMOTE}:${SPACES_BUCKET}/${TIER}/$(basename "$ARCHIVE")"
log "Upload vers $REMOTE_PATH..."
rclone copy "$ARCHIVE" "${RCLONE_REMOTE}:${SPACES_BUCKET}/${TIER}/" \
  --s3-upload-cutoff 0 \
  --progress=false \
  --stats=0 2>&1 | tee -a "$LOG_FILE"

log "Upload terminé"

# ─────────────────────────────────────────────────────────────────────────────
# 5) Healthchecks.io success ping (avec log en body pour debug)
# ─────────────────────────────────────────────────────────────────────────────
curl -fsS -m 10 --retry 3 -o /dev/null \
  --data-binary "@$LOG_FILE" \
  "https://hc-ping.com/${HEALTHCHECKS_BACKUP_UUID}"

log "Backup terminé avec succès"
