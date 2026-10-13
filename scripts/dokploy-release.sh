#!/usr/bin/env bash
# Shared contract for KLASSCI College release automation. Copy kept in both repositories.
# Run on the Contabo host, through a restricted deployment SSH account.
set -Eeuo pipefail

component="${1:-}"
image="${2:-}"
project="klassci-college-prod"
stack="/etc/dokploy/compose/${project}/code"
public="https://college.klassci.com"

case "$component" in
  frontend)
    variable="KLASSCI_FRONTEND_IMAGE"
    services=(frontend)
    ;;
  backend)
    variable="KLASSCI_BACKEND_IMAGE"
    services=(backend worker beat)
    ;;
  *) echo "Invalid service. Expected frontend or backend." >&2; exit 2 ;;
esac
if [[ ! "$image" =~ ^klassci-college-(frontend|backend):git-[0-9a-f]{40}$ ]] \
   || [[ "$image" != klassci-college-"$component":* ]]; then
  echo "Invalid immutable release image tag" >&2
  exit 2
fi

cd "$stack"
[[ -f docker-compose.yml && -f .env ]] || { echo "Active Dokploy compose not found"; exit 1; }
command -v flock >/dev/null
command -v python3 >/dev/null
command -v docker >/dev/null
command -v curl >/dev/null
# BOTH repositories contend for the SAME remote lock; GitHub concurrency alone
# cannot prevent frontend/backend releases from racing across repositories.
exec 9>/tmp/klassci-college-prod-release.lock
flock -x -w 600 9 || { echo "Another release holds the lock"; exit 1; }
docker compose -p "$project" config --quiet >/dev/null
for volume in linux_klassci_mysql linux_klassci_redis; do
  docker volume inspect "$volume" >/dev/null
done
docker image inspect "$image" >/dev/null

# Resolve the effective image from the ACTIVE compose, not the versioned template.
read_image() {
  docker compose -p "$project" config --format json | python3 -c \
    'import json,sys; c=json.load(sys.stdin); print(c["services"][sys.argv[1]]["image"])' "$1"
}
previous="$(read_image "$component")"
[[ "$previous" != "" ]] || { echo "Previous image missing"; exit 1; }
docker image inspect "$previous" >/dev/null || {
  echo "Rollback image not present locally; refusing deployment"; exit 1;
}
if [[ "$previous" == "$image" ]]; then
  echo "Release already selected: $image"
  exit 0
fi

# Verify that all targeted services truly respect their KLASSCI_*_IMAGE variable.
for service in "${services[@]}"; do
  resolved="$(env "$variable=$image" docker compose -p "$project" config --format json |
    python3 -c 'import json,sys; c=json.load(sys.stdin); print(c["services"][sys.argv[1]]["image"])' "$service")"
  [[ "$resolved" == "$image" ]] || {
    echo "Live compose service $service does not honor $variable; aborting"; exit 1;
  }
done

# Never deploy onto an already broken production.
curl -fsS --max-time 10 "$public/svc/health" >/dev/null
curl -fsS --max-time 10 "$public/login" >/dev/null

if [[ "$component" == backend ]]; then
  # A confirmed restore dry-run and backward-compatible Alembic revisions are
  # operational preconditions. Set these as GitHub environment variables only
  # after verifying the actual Contabo backups and an isolated restore.
  [[ "${KLASSCI_MIGRATIONS_APPROVED:-}" == yes ]] || {
    echo "Backend migrations need explicit approval"; exit 1;
  }
  [[ "${KLASSCI_RESTORE_VERIFIED:-}" == yes ]] || {
    echo "A tested database restore is required"; exit 1;
  }
  backup_script="${KLASSCI_BACKUP_SCRIPT:-$HOME/klassci-backup-mysql.sh}"
  [[ -f "$backup_script" ]] || { echo "MySQL backup script missing"; exit 1; }
  echo "Running production MySQL backup before migrations"
  bash "$backup_script"
  echo "Running tenant migrations using the new backend image"
  # --no-deps is essential: NEVER recreate mysql, redis, proxy, or WOURI.
  # One-off container does not replace live backend. MySQL DDL may not roll back.
  KLASSCI_BACKEND_IMAGE="$image" docker compose -p "$project" \
    run --rm --no-deps backend python -m app.cli.migrate_all head
fi

# The live stack uses a .env image pointer; persist the new pin, otherwise
# the next Dokploy compose redeployment could silently restore the old image.
backup="$(mktemp -p "$stack" .klassci-release-env.XXXXXX)"
chmod 600 "$backup"
cp -p .env "$backup"
changed=0
rollback() {
  rc=$?
  trap - ERR
  if [[ "$changed" == 1 ]]; then
    echo "Release failed; restoring previous compose image pin (not DB schema)" >&2
    cp -p "$backup" .env
    docker compose -p "$project" up -d --no-deps --force-recreate "${services[@]}" ||
      echo "WARNING: automatic application rollback failed; intervention required" >&2
  fi
  rm -f "$backup"
  exit "$rc"
}
trap rollback ERR

python3 - "$variable" "$image" <<'PY'
import os
import pathlib
import re
import sys
import tempfile

key, image = sys.argv[1:]
path = pathlib.Path(".env")
source = path.read_text()
pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
if len(pattern.findall(source)) != 1:
    raise SystemExit(f"Expected exactly one {key} entry in active .env")
updated = pattern.sub(lambda _: f"{key}={image}", source)
fd, tmp = tempfile.mkstemp(prefix=".klassci-env-", dir=path.parent)
try:
    os.fchmod(fd, path.stat().st_mode & 0o777)
    with os.fdopen(fd, "w") as out:
        out.write(updated)
    os.replace(tmp, path)
finally:
    if os.path.exists(tmp):
        os.unlink(tmp)
PY
changed=1

docker compose -p "$project" config --quiet >/dev/null
docker compose -p "$project" up -d --no-deps --force-recreate "${services[@]}"

# Wait for the selected container and public smoke probes; no fake zero downtime.
healthy=0
for attempt in $(seq 1 30); do
  container="$(docker compose -p "$project" ps -q "$component")"
  if [[ -n "$container" ]] && [[ "$(docker inspect -f '${.State.Running}' "$container")" == true ]] &&
     curl -fsS --max-time 6 "$public/svc/health" >/dev/null 2>&1 &&
     curl -fsS --max-time 6 "$public/login" >/dev/null 2>&1; then
    healthy=1
    break
  fi
  sleep 3
done
[[ "$healthy" == 1 ]] || { echo "Post-release health probes failed"; false; }

changed=0
trap - ERR
rm -f "$backup"
echo "KLASSCI $component deployed: $image"
