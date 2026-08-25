#!/usr/bin/env python3
"""Recreate only the Dokploy proxy with a host-absolute Caddyfile bind."""
from __future__ import annotations

import subprocess
from pathlib import Path

CODE = Path("/etc/dokploy/compose/klassci-college-prod/code")
COMPOSE = CODE / "docker-compose.yml"
OLD = "      - ./Caddyfile:/etc/caddy/Caddyfile:ro"
NEW = "      - /etc/dokploy/compose/klassci-college-prod/code/Caddyfile:/etc/caddy/Caddyfile:ro"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    res = subprocess.run(cmd, text=True, capture_output=True)
    if res.stdout:
        print(res.stdout.rstrip(), flush=True)
    if res.stderr:
        print(res.stderr.rstrip(), flush=True)
    if check and res.returncode != 0:
        raise SystemExit(res.returncode)
    return res


def main() -> int:
    text = COMPOSE.read_text(encoding="utf-8")
    if OLD in text:
        COMPOSE.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
        print("patched compose bind")
    elif NEW in text:
        print("compose already patched")
    else:
        raise SystemExit("unexpected Caddyfile bind")

    run(["docker", "rm", "-f", "klassci-college-prod-proxy-1"], check=False)
    run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "--project-directory",
            str(CODE),
            "-p",
            "klassci-college-prod",
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "proxy",
        ]
    )
    run(["docker", "ps", "-a", "--filter", "name=klassci-college-prod-proxy", "--format", "{{.Names}} {{.Status}} {{.Ports}}"])
    run(["docker", "inspect", "klassci-college-prod-proxy-1", "--format", "{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
