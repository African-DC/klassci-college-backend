#!/usr/bin/env python3
"""Register the live KLASSCI College stack as a Dokploy Compose project.

Keeps existing MySQL/Redis volumes. Does not touch Wourri.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SRC = Path("/opt/apps/klassci-college/deploy/linux")
COMPOSE_SRC = SRC / "docker-compose.dokploy.yml"
CADDY_SRC = SRC / "Caddyfile"
ENV_SRC = SRC / ".env"
DOKPLOY_CTN = None


def run(cmd: list[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def sh(cmd: str, check: bool = True) -> str:
    res = run(["bash", "-lc", cmd], check=check)
    return (res.stdout or "").strip()


def find_container(prefixe: str) -> str:
    """Le conteneur dont le nom commence par `prefixe`.

    Les noms portent un identifiant de tâche Swarm — `dokploy-postgres.1.esnff…`
    — qui change à chaque redéploiement. Le coder en dur marche jusqu'au jour
    où le service redémarre.
    """
    out = sh("docker ps --filter name=%s --format '{{.Names}}'" % prefixe)
    if not out:
        raise SystemExit("conteneur introuvable : %s" % prefixe)
    return out.splitlines()[0]


def pg(sql: str) -> str:
    """Interroger la base de Dokploy, à travers son conteneur postgres."""
    conteneur = find_container("dokploy-postgres")
    return sh(
        "docker exec " + conteneur + " psql -U dokploy -d dokploy -At -c " + json.dumps(sql)
    )


def main() -> int:
    if not COMPOSE_SRC.exists() or not ENV_SRC.exists():
        raise SystemExit("missing compose/env on host")

    print("== volumes")
    vols = sh("docker volume ls --format '{{.Name}}'")
    for needed in ("linux_klassci_mysql", "linux_klassci_redis"):
        if needed not in vols.splitlines():
            raise SystemExit(f"missing volume {needed}")
        print("ok", needed)

    print("== wourri still up")
    print(sh("docker ps --filter name=wourri --format '{{.Names}} {{.Status}}'"))

    print("== dokploy schema peek")
    tables = pg(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename ~ 'project|compose|environment|user' ORDER BY 1;"
    )
    print(tables)

    print("== existing projects")
    print(pg("SELECT column_name FROM information_schema.columns WHERE table_name='project' ORDER BY ordinal_position;"))
    try:
        print(pg("SELECT \"projectId\", name FROM project;"))
    except subprocess.CalledProcessError as exc:
        print("project query failed", exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
