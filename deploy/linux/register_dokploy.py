#!/usr/bin/env python3
"""Register KLASSCI College in Dokploy and adopt the live stack."""
from __future__ import annotations

import datetime as dt
import secrets
import string
import subprocess
import sys
from pathlib import Path

ORG_ID = "34cKM_BzmWx70IyUxv0K2"
SRC = Path("/opt/apps/klassci-college/deploy/linux")
COMPOSE_FILE = SRC / "docker-compose.dokploy.yml"
ENV_FILE = SRC / ".env"
CADDY_FILE = SRC / "Caddyfile"
PG = "dokploy-postgres.1.esnff5rkgy8t8jjeoz92qfllr"
APP_NAME = "klassci-college-prod"
DEST = Path(f"/etc/dokploy/compose/{APP_NAME}/code")


def nanoid(n: int = 21) -> str:
    alphabet = string.ascii_letters + string.digits + "_-"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run(cmd: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=input_text, text=True, capture_output=True)


def psql(sql: str) -> str:
    res = run(["docker", "exec", "-i", PG, "psql", "-U", "dokploy", "-d", "dokploy", "-At"], sql)
    if res.returncode != 0:
        raise SystemExit(res.stderr or res.stdout)
    return (res.stdout or "").strip()


def docker_write(host_path: str, content: str, mode: str = "644") -> None:
    res = run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            "/etc/dokploy/compose:/dest",
            "alpine:3.20",
            "sh",
            "-c",
            f"mkdir -p /dest/{APP_NAME}/code && cat > /dest/{APP_NAME}/code/{Path(host_path).name}",
        ],
        content,
    )
    if res.returncode != 0:
        raise SystemExit(res.stderr or res.stdout)


def docker_install_files(compose_text: str, env_text: str, caddy_text: str) -> None:
    script = r"""
set -eu
mkdir -p /dest/%s/code
cat > /dest/%s/code/docker-compose.yml <<'EOF_COMPOSE'
%s
EOF_COMPOSE
cat > /dest/%s/code/Caddyfile <<'EOF_CADDY'
%s
EOF_CADDY
cat > /dest/%s/code/.env <<'EOF_ENV'
%s
EOF_ENV
chmod 644 /dest/%s/code/docker-compose.yml /dest/%s/code/Caddyfile
chmod 600 /dest/%s/code/.env
""" % (
        APP_NAME,
        APP_NAME,
        compose_text,
        APP_NAME,
        caddy_text,
        APP_NAME,
        env_text,
        APP_NAME,
        APP_NAME,
        APP_NAME,
    )
    res = run(
        ["docker", "run", "--rm", "-v", "/etc/dokploy/compose:/dest", "alpine:3.20", "sh", "-c", script]
    )
    if res.returncode != 0:
        raise SystemExit(res.stderr or res.stdout)


def main() -> int:
    for path in (COMPOSE_FILE, ENV_FILE, CADDY_FILE):
        if not path.exists():
            raise SystemExit(f"missing {path}")

    print("== volumes")
    vols = run(["docker", "volume", "ls", "--format", "{{.Name}}"]).stdout.splitlines()
    for needed in ("linux_klassci_mysql", "linux_klassci_redis"):
        if needed not in vols:
            raise SystemExit(f"missing volume {needed}")
        print("ok", needed)

    print("== wourri")
    print(run(["docker", "ps", "--filter", "name=wourri", "--format", "{{.Names}} {{.Status}}"]).stdout)

    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    env_text = ENV_FILE.read_text(encoding="utf-8")
    caddy_text = CADDY_FILE.read_text(encoding="utf-8")
    if "$$" in compose_text or "$$" in env_text:
        raise SystemExit("dollar-quoting conflict in files")

    print("== install dokploy files")
    docker_install_files(compose_text, env_text, caddy_text)
    print(run(["docker", "run", "--rm", "-v", "/etc/dokploy/compose:/dest", "alpine:3.20", "ls", "-la", f"/dest/{APP_NAME}/code"]).stdout)

    existing = psql("SELECT name FROM project;")
    if "klassci-college" in existing.splitlines():
        print("project already exists")
        print(psql("SELECT \"projectId\", name FROM project WHERE name = 'klassci-college';"))
        return 0

    project_id = nanoid()
    env_id = nanoid()
    compose_id = nanoid()
    created = now()
    sql = f"""
INSERT INTO project ("projectId", name, description, "createdAt", env, "organizationId")
VALUES ('{project_id}', 'klassci-college', 'KLASSCI College production', '{created}', '', '{ORG_ID}');

INSERT INTO environment ("environmentId", name, description, "createdAt", "projectId", env, "isDefault")
VALUES ('{env_id}', 'production', 'Production Contabo', '{created}', '{project_id}', '', true);

INSERT INTO compose (
  "composeId", name, "appName", description, env, "composeFile", "refreshToken",
  "sourceType", "composeType", "autoDeploy", command, "composePath", "composeStatus",
  "createdAt", suffix, randomize, "isolatedDeployment", "enableSubmodules",
  "isolatedDeploymentsVolume", "environmentId", "createEnvFile"
) VALUES (
  '{compose_id}', 'klassci-college', '{APP_NAME}', 'College stack with existing volumes',
  $${env_text}$$,
  $${compose_text}$$,
  '{nanoid(32)}', 'raw', 'docker-compose', false, '', './docker-compose.yml', 'done',
  '{created}', '', false, false, false, false, '{env_id}', true
);
"""
    print("== insert")
    print(psql(sql) or "insert ok")
    print("ids", project_id, env_id, compose_id)
    print(psql("SELECT name FROM project ORDER BY name;"))
    print(psql("SELECT name, \"appName\" FROM compose ORDER BY name;"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
