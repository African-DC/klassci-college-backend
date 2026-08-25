#!/usr/bin/env python3
"""Adopt the live College stack under the Dokploy compose project.

Stops the manual 'linux' project without deleting volumes, then starts
the Dokploy compose using the existing MySQL/Redis volumes.
"""
from __future__ import annotations

import subprocess
import sys
import time


OLD = "/opt/apps/klassci-college/deploy/linux"
NEW_CODE = "/etc/dokploy/compose/klassci-college-prod/code"
NEW_PROJECT = "klassci-college-prod"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    res = subprocess.run(cmd, text=True, capture_output=True)
    if res.stdout:
        print(res.stdout.rstrip())
    if res.stderr:
        print(res.stderr.rstrip())
    if check and res.returncode != 0:
        raise SystemExit(res.returncode)
    return res


def main() -> int:
    print("== precheck wourri")
    run(["docker", "ps", "--filter", "name=wourri", "--format", "{{.Names}} {{.Status}}"])
    print("== old stack")
    run(["docker", "compose", "-f", f"{OLD}/docker-compose.yml", "--project-directory", OLD, "ps"], check=False)

    print("== down old project without volumes")
    run(["docker", "compose", "-f", f"{OLD}/docker-compose.yml", "--project-directory", OLD, "down", "--remove-orphans"])

    print("== volumes still present")
    run(["docker", "volume", "inspect", "linux_klassci_mysql", "linux_klassci_redis", "--format", "{{.Name}} {{.Mountpoint}}"])

    print("== up dokploy project")
    run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "-v",
            f"{NEW_CODE}:/work",
            "-w",
            "/work",
            "docker:27-cli",
            "compose",
            "-p",
            NEW_PROJECT,
            "up",
            "-d",
            "--remove-orphans",
        ]
    )

    print("== wait")
    time.sleep(12)
    run(["docker", "ps", "--format", "{{.Names}} {{.Status}} {{.Ports}}"])
    print("== wourri after")
    run(["docker", "ps", "--filter", "name=wourri", "--format", "{{.Names}} {{.Status}}"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
