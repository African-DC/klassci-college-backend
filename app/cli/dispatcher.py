"""Local vs Remote dispatcher for CLI commands.

Local mode imports `app.services.*` directly — only works on a host where
the backend code is installed (EC2 prod or dev machine with venv).

Remote mode talks to the FastAPI backend over HTTP via httpx, using a
PAT from the OS keyring. Works from any machine, including AI agents.

Subcommands stay clean: they receive a Dispatcher and call the named
operation; the implementation is selected once at the root group level.
"""

from __future__ import annotations

from typing import Any, Protocol

import click
import httpx

from app.cli.auth import get_token


class Dispatcher(Protocol):
    mode: str

    async def get(self, path: str, **params: Any) -> Any: ...
    async def post(self, path: str, json_body: Any | None = None) -> Any: ...
    async def delete(self, path: str) -> int: ...


class RemoteDispatcher:
    mode = "remote"

    def __init__(self, api_url: str, profile: str = "default") -> None:
        self.api_url = api_url.rstrip("/")
        token = get_token(profile)
        if not token:
            raise click.ClickException(
                f"Pas de token pour le profil '{profile}'. "
                f"Lance d'abord : klassci login --profile {profile}"
            )
        self.client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    async def get(self, path: str, **params: Any) -> Any:
        resp = await self.client.get(path, params=params or None)
        return _unwrap(resp)

    async def post(self, path: str, json_body: Any | None = None) -> Any:
        resp = await self.client.post(path, json=json_body)
        return _unwrap(resp)

    async def delete(self, path: str) -> int:
        resp = await self.client.delete(path)
        if resp.status_code >= 400:
            raise click.ClickException(f"HTTP {resp.status_code}: {resp.text}")
        return resp.status_code

    async def aclose(self) -> None:
        await self.client.aclose()


class LocalDispatcher:
    """Imports app.services.* directly. Skips network and HTTP middleware.

    Currently unused by Sprint 1.3 commands (all use Remote). Wired up
    when CLI-3 / CLI-4 introduces the local-only ops (alembic, celery).
    """

    mode = "local"

    async def get(self, path: str, **params: Any) -> Any:
        raise NotImplementedError("Local mode wiring lands with CLI-3+")

    async def post(self, path: str, json_body: Any | None = None) -> Any:
        raise NotImplementedError("Local mode wiring lands with CLI-3+")

    async def delete(self, path: str) -> int:
        raise NotImplementedError("Local mode wiring lands with CLI-3+")


def _unwrap(resp: httpx.Response) -> Any:
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise click.ClickException(f"HTTP {resp.status_code}: {detail}")
    if resp.status_code == 204:
        return None
    return resp.json()
