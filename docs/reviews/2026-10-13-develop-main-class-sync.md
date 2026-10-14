# Review — develop/main class exports reconciliation

Scope: Restored main-proven class roster Word endpoint and service, validated-enrollment counts, test cases, and teacher Word invalid-logo fallback.

## Verification performed

- Compared `main` and `develop` file contents rather than relying on commit counts.
- Restored only the verified class-export and teacher-export differences from `main` into an isolated branch based on `develop`.
- Kept `.github/workflows/production-release.yml` and `docs/DOKPLOY_AUTODEPLOY.md` from `develop` unchanged.
- Checked the corresponding CHANGELOG and generated release-feed entries.
- Checked diff boundaries; no database migrations, secrets, Docker Compose configuration, volumes, or deployment triggers were added in this PR.
- Required CI, security, and Alembic idempotence validation to pass on the final head SHA before merging.

## Deployment safeguard

This PR targets `develop` only. Do not deploy to production as part of this reconciliation. Keep `main` unchanged unless and until a separate reviewed release is warranted.
