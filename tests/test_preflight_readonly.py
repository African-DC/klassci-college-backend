"""Non-destructive checks for the Compose runtime inventory report."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "preflight_readonly", ROOT / "deploy" / "linux" / "preflight_readonly.py"
)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def container(
    service: str,
    *,
    running: bool = True,
    health: str | None = None,
    image: str = "sha256:base",
    mounts: tuple[str, ...] = (),
) -> dict:
    state = {"Running": running}
    if health is not None:
        state["Health"] = {"Status": health}
    return {
        "Config": {
            "Labels": {"com.docker.compose.service": service},
            "Image": "klassci:prod",
            "Env": ["MYSQL_PASSWORD=SHOULD_NEVER_APPEAR_IN_REPORT"],
        },
        "State": state,
        "Image": image,
        "Mounts": [
            {"Type": "volume", "Name": volume, "Source": "/secret/source"}
            for volume in mounts
        ],
        "RestartCount": 0,
    }


def healthy_stack() -> list[dict]:
    return [
        container("mysql", health="healthy", mounts=("linux_klassci_mysql",)),
        container("redis", health="healthy", mounts=("linux_klassci_redis",)),
        container("backend", health="healthy", mounts=("linux_klassci_uploads",)),
        container("worker", mounts=("linux_klassci_uploads",)),
        container("beat"),
        container("frontend", image="sha256:frontend"),
        container("proxy", image="sha256:proxy"),
    ]


def test_live_stack_can_be_inspected_without_exposing_secrets() -> None:
    result = probe.review(healthy_stack(), set(probe.VOLUMES))
    assert not result["errors"]
    assert len(result["services"]) == 7
    assert any("handoff" in warning for warning in result["warnings"])
    assert "SHOULD_NEVER_APPEAR" not in repr(result)
    assert "/secret/source" not in repr(result)


def test_missing_uploads_or_mysql_volume_blocks_go() -> None:
    result = probe.review(healthy_stack(), {"linux_klassci_redis"})
    assert any("linux_klassci_mysql" in error for error in result["errors"])
    assert any("linux_klassci_uploads" in error for error in result["errors"])


def test_worker_image_must_match_backend_and_beat() -> None:
    stack = healthy_stack()
    stack[3]["Image"] = "sha256:wrong-worker"
    result = probe.review(stack, set(probe.VOLUMES))
    assert any("même image ID" in error for error in result["errors"])


def test_unhealthy_mysql_and_missing_backend_mount_are_blocking() -> None:
    stack = healthy_stack()
    stack[0]["State"]["Health"]["Status"] = "unhealthy"
    stack[2]["Mounts"] = []
    result = probe.review(stack, set(probe.VOLUMES))
    assert any("mysql" in error and "healthcheck" in error for error in result["errors"])
    assert any("backend" in error and "linux_klassci_uploads" in error for error in result["errors"])


def test_duplicate_services_are_not_silently_accepted() -> None:
    stack = healthy_stack()
    stack.append(stack[0].copy())
    result = probe.review(stack, set(probe.VOLUMES))
    assert any("mysql" in error and "2 conteneur(s)" in error for error in result["errors"])
