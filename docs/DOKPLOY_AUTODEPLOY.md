# KLASSCI College — Controlled Dokploy deployment

## Status

This workflow is intentionally **OFF** until server preflight, restore drill, and
GitHub secrets have been completed. It does not change production merely by
merging the configuration PR. It runs on main only after the repository-level
variable KLASSCI_AUTO_DEPLOY has the exact value enabled.

Two repositories use the SAME release protocol:
- African-DC/klassci-college-frontend => service frontend only.
- African-DC/klassci-college-backend => services backend, worker, beat.

Production is the EXISTING Dokploy Compose klassci-college-prod, not a new
Compose project. The compose file at
/etc/dokploy/compose/klassci-college-prod/code/docker-compose.yml
and .env are the source of truth. Never replace them blindly with the versioned
deploy/linux/docker-compose.dokploy.yml without inventorying differences.

No Docker Compose down, no down -v, no MySQL/Redis recreation, no WOURI changes.

## 1. Before enabling: verify server

Access the existing Dokploy project and use the approved SSH account. On Contabo,
read without changing anything:

    cd /etc/dokploy/compose/klassci-college-prod/code
    docker compose -p klassci-college-prod ps
    docker compose -p klassci-college-prod config --services
    docker compose -p klassci-college-prod config --images
    grep -E '^KLASSCI_(BACKEND|FRONTEND)_IMAGE=' .env | cut -d= -f1
    docker volume inspect linux_klassci_mysql linux_klassci_redis
    test -f "$HOME/klassci-backup-mysql.sh"

Do NOT show/share .env content: it holds secrets. Both image variables must
actually influence the compose images of all targeted services. The script
checks this and refuses incompatible live infrastructure rather than guessing.

## 2. Verify recoverability (backend critical)

Run an authenticated full MySQL backup for ALL real tenant databases.
Verify that local and off-site copies exist, and test the restore with
INDEPENDENT volumes/databases on staging. Never attach a test stack to the
production linux_klassci_* volumes. Compare table counts, tenant list and
alembic_version for local plus all schools. Verify uploaded files separately.

Simulate any new Alembic revision using that restored copy and the exact
release image. Some MySQL DDL cannot roll back. Make sure changes are
backward-compatible before live backend/worker replacement; if not, plan a
maintenance window and manual controlled rollout.

The existing server backup script is expected at
$HOME/klassci-backup-mysql.sh; optionally set KLASSCI_BACKUP_SCRIPT in the
remote SSH account environment to an approved alternative. The script is
invoked BEFORE running python -m app.cli.migrate_all head in a one-off container
built from the new backend image. A failed migration stops deployment and
requires examination of possible partial schema changes. NO automatic DB
downgrade is attempted.

## 3. GitHub repository setup (both repositories)

Create GitHub Environment: production. Limit deployment branches to main,
and preferably require manual approval for the first few releases.

Create repository-level variable:
- KLASSCI_AUTO_DEPLOY = disabled (initially); change to enabled ONLY after dry-run.

Set GitHub Environment variables:
- KLASSCI_DEPLOY_HOST = verified Contabo hostname/IP
- KLASSCI_DEPLOY_USER = restricted SSH deployment account
- Backend ONLY: KLASSCI_MIGRATIONS_APPROVED = yes after explicit approval
- Backend ONLY: KLASSCI_RESTORE_VERIFIED = yes after restoring a full backup

Set GitHub Environment secrets:
- KLASSCI_SSH_PRIVATE_KEY = dedicated private SSH deploy key (not copied into git)
- KLASSCI_SSH_KNOWN_HOSTS = trusted pinned OpenSSH host-key entry.

Record the host's fingerprint from a separately verified trusted source; never
accept the first host key from an unauthenticated network scan.
SSH account must have Docker privileges and write permission to the live .env.
Do not use an unrestricted root SSH account or put production DB passwords
in GitHub Actions.

If restrictions or required secrets are missing, workflow fails BEFORE
the Docker image is built or deployment is attempted.

## 4. Deployment sequence

PRs remain mandatory (feature/* -> develop -> staging -> main).
Existing CI and branch protections remain the merge gates.
A push to main with activation enabled triggers:

1. syntax check of release script.
2. Docker image build from this exact commit with git-SHA image tag.
3. image delivery via encrypted SSH (docker save/load).
4. shared Linux flock lock across frontend/backend repositories.
5. validate real Dokploy Compose and persistent MySQL/Redis volumes.
6. verify new tag overrides only the intended services.
7. backend: fresh backup, then migrate all tenant databases with NEW image.
8. atomically change matching image pointer in the active .env.
9. docker compose up -d --no-deps --force-recreate (targeted services only).
10. probe public /svc/health, /login and target container running states.

An application failure restores previous image pointer and attempts a targeted
service rollback; it NEVER rewinds database migrations or user writes.
A simple Compose recreate may cause a brief interruption (not zero downtime).

## 5. Release recovery

On failure, inspect Actions logs and docker compose ps / service logs first.
Do not retry Alembic blindly if a migration was interrupted. Confirm
alembic_version and actual schema for EACH tenant. Roll back only the
application image when the old application is compatible with the new schema.
Restore databases only via a separately planned, audited operation;
a DB restore overwrites school data written since the backup.

The release script is run from its GitHub commit over SSH, not copied into
the live Dokploy-managed project. Backend and frontend share one /tmp flock.
If Docker Compose was independently changed in Dokploy, repeat the read-only
preflight before re-enabling.

## 6. Smoke test and observability

Verify login and /svc/health plus an authenticated school scenario: Rostan
Bouake enrollment, note lookup and saved student photo. Verify Celery worker
and beat are running and that previously uploaded logos/files persist.
Add Sentry alerting and routine restore-test checks before declaring full CD.

**The current PRs do not deploy anything to production.**
