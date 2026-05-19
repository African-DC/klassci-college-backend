"""CLI dispatcher access without importing the root group module.

Lives in its own module to break the cyclic import that arises when
command modules need ``get_dispatcher`` (defined alongside the root
group). Both ``klassci.py`` and ``commands/*.py`` import from here.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import click

from app.cli.dispatcher import LocalDispatcher, RemoteDispatcher

if TYPE_CHECKING:
    from app.cli.dispatcher import Dispatcher


def get_dispatcher(ctx: click.Context) -> Dispatcher:
    """Lazy: build the dispatcher only when an authenticated subcommand needs it."""
    if "dispatcher" in ctx.obj:
        return ctx.obj["dispatcher"]
    mode = ctx.obj.get("mode") or os.getenv("KLASSCI_MODE", "remote")
    if mode == "local":
        ctx.obj["dispatcher"] = LocalDispatcher()
    else:
        ctx.obj["dispatcher"] = RemoteDispatcher(
            api_url=ctx.obj["api_url"], profile=ctx.obj["profile"]
        )
    return ctx.obj["dispatcher"]
