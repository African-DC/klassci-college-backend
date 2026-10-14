#!/usr/bin/env python3
"""Read-only inventory of the LIVE KLASSCI College Docker Compose services.

Does not access SQL data, dump secrets, run migrations, build images or restart
containers. This is one PRE-deployment gate, not proof of backup restorability.
Run on the Contabo host with Docker read permissions.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from typing import Any

SERVICES = ("mysql", "redis", "backend", "worker", "beat", "frontend", "proxy")
VOLUMES = ("linux_klassci_mysql", "linux_klassci_redis", "linux_klassci_uploads")
REQUIRED_MOUNTS = {
    "mysql": ("linux_klassci_mysql",),
    "redis": ("linux_klassci_redis",),
    "backend": ("linux_klassci_uploads",),
    "worker": ("linux_klassci_uploads",),
}
HEALTH_REQUIRED = ("mysql", "redis", "backend")


def docker(*arguments: str) -> str:
    result = subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        check=True,
        timeout=35,
    )
    return result.stdout.strip()


def review(containers: list[dict[str, Any]], volumes: set[str]) -> dict[str, Any]:
    """Evaluate docker-inspect metadata; NEVER include Environment or mounts paths."""
    errors: list[str] = []
    warnings: list[str] = []
    services: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in containers:
        labels = item.get("Config", {}).get("Labels") or {}
        service = labels.get("com.docker.compose.service")
        if service in SERVICES:
            grouped[service].append(item)

    for volume in VOLUMES:
        if volume not in volumes:
            errors.append(f"Volume externe absent : {volume}")

    for service in SERVICES:
        matches = grouped.get(service, [])
        if len(matches) != 1:
            errors.append(
                f"{service} : {len(matches)} conteneur(s) dans le projet "
                "(un seul attendu ; vérifier les anciens conteneurs)"
            )
            continue
        item = matches[0]
        state = item.get("State") or {}
        image_id = item.get("Image") or ""
        image_name = item.get("Config", {}).get("Image") or ""
        mounts = {
            mount.get("Name")
            for mount in item.get("Mounts", [])
            if mount.get("Type") == "volume"
        }
        health = (state.get("Health") or {}).get("Status")
        running = bool(state.get("Running"))
        services[service] = {
            "running": running,
            "health": health or "non défini",
            "image": image_name,
            "image_id": image_id[:19],
            "restarts": int(item.get("RestartCount") or 0),
            "mounts": sorted(name for name in mounts if name in VOLUMES),
        }
        if not running:
            errors.append(f"{service} : conteneur arrêté")
        if service in HEALTH_REQUIRED and health != "healthy":
            errors.append(f"{service} : healthcheck attendu healthy, trouvé {health}")
        if health == "unhealthy":
            errors.append(f"{service} : healthcheck unhealthy")
        if service in ("frontend", "worker", "beat") and not health:
            warnings.append(
                f"{service} : aucun healthcheck (running ne prouve pas "
                "le fonctionnement métier)"
            )
        for volume in REQUIRED_MOUNTS.get(service, ()):
            if volume not in mounts:
                errors.append(f"{service} : montage requis absent : {volume}")

    ids = [grouped[name][0].get("Image") for name in ("backend", "worker", "beat")
           if len(grouped[name]) == 1]
    if len(ids) == 3 and (not all(ids) or len(set(ids)) != 1):
        errors.append("backend, worker et beat doivent exécuter la même image ID")

    # Optional handoff channel exists in Git version but not necessarily in Raw.
    if all(len(grouped[name]) == 1 for name in ("backend", "worker")):
        handoffs = []
        for service in ("backend", "worker"):
            container = grouped[service][0]
            names = {
                mount.get("Name")
                for mount in container.get("Mounts", [])
                if mount.get("Type") == "volume"
            }
            has_handoff = any(
                name and "handoff" in name.lower() for name in names
            )
            handoffs.append(has_handoff)
        if not all(handoffs):
            warnings.append(
                "Volume handoff non partagé backend/worker ; comparer la stack Raw "
                "au Compose versionné avant de toucher aux dépôts de photos"
            )

    return {"errors": errors, "warnings": warnings, "services": services,
            "volume_presence": {name: name in volumes for name in VOLUMES}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project", default="klassci-college-prod",
        help="Label Docker Compose com.docker.compose.project du projet EXISTANT",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Rapport JSON filtré sans secrets / variables d'environnement",
    )
    args = parser.parse_args()
    if not args.project or "/" in args.project:
        parser.error("Nom de projet invalide")
    try:
        ids = docker(
            "ps", "-aq",
            "--filter", f"label=com.docker.compose.project={args.project}",
        ).splitlines()
        if not ids:
            print(
                f"Aucun conteneur Compose pour {args.project}. "
                "Vérifier docker compose ls, ne PAS créer de projet.",
                file=sys.stderr,
            )
            return 2
        inspected = json.loads(docker("inspect", *ids))
        volumes = set(
            docker("volume", "ls", "--format", "{{.Name}}").splitlines()
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"Inventaire Docker impossible : {type(exc).__name__}", file=sys.stderr)
        return 2

    outcome = review(inspected, volumes)
    free_gib = shutil.disk_usage("/").free / (1024**3)
    outcome["host_free_disk_gib"] = round(free_gib, 1)
    if free_gib < 5:
        outcome["warnings"].append("Moins de 5 Gio disponibles sur / ; vérifier la place des builds")
    outcome["scope"] = "LECTURE SEULE — ni sauvegarde/restauration ni migrations vérifiées"
    if args.json:
        print(json.dumps(outcome, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"KLASSCI College — Docker Compose projet {args.project}")
        for service, info in outcome["services"].items():
            print(
                f"{service:9} running={info['running']} health={info['health']} "
                f"restarts={info['restarts']} image={info['image_id']}"
            )
        for message in outcome["warnings"]:
            print("ATTENTION :", message)
        for message in outcome["errors"]:
            print("ERREUR :", message)
        print(outcome["scope"])
    return 1 if outcome["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
