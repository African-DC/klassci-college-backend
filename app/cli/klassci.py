"""``klassci`` — KLASSCI College admin CLI.

Invoke via ``python -m app.cli.klassci`` (a console_scripts entry point
will land once the project ships a ``[project]`` section in pyproject).
"""

from __future__ import annotations

import os

import click

from app.cli.commands.doctor import doctor
from app.cli.commands.login import login
from app.cli.commands.pat import pat_group
from app.cli.commands.tenant import tenant_group
from app.cli.dispatcher import LocalDispatcher, RemoteDispatcher

VERSION = "0.1.0"


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(VERSION, prog_name="klassci")
@click.option(
    "--local", "mode", flag_value="local", help="Direct service imports (EC2 / dev only)."
)
@click.option("--remote", "mode", flag_value="remote", help="HTTP API (default; uses keyring PAT).")
@click.option(
    "--api-url",
    envvar="KLASSCI_API_URL",
    default="https://college.klassci.com",
    show_default=True,
)
@click.option(
    "--profile",
    envvar="KLASSCI_PROFILE",
    default="default",
    help="Auth profile name in keyring.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["human", "json", "table"], case_sensitive=False),
    default="human",
    show_default=True,
)
@click.pass_context
def cli(
    ctx: click.Context,
    mode: str | None,
    api_url: str,
    profile: str,
    output_format: str,
) -> None:
    """KLASSCI College admin CLI — multi-tenant ops + diagnostics."""
    ctx.ensure_object(dict)
    ctx.obj["mode"] = mode or os.getenv("KLASSCI_MODE", "remote")
    ctx.obj["api_url"] = api_url
    ctx.obj["profile"] = profile
    ctx.obj["format"] = output_format


def get_dispatcher(ctx: click.Context):
    """Lazy: build the dispatcher only when an authenticated subcommand needs it."""
    if "dispatcher" in ctx.obj:
        return ctx.obj["dispatcher"]
    if ctx.obj["mode"] == "local":
        ctx.obj["dispatcher"] = LocalDispatcher()
    else:
        ctx.obj["dispatcher"] = RemoteDispatcher(
            api_url=ctx.obj["api_url"], profile=ctx.obj["profile"]
        )
    return ctx.obj["dispatcher"]


cli.add_command(login)
cli.add_command(tenant_group)
cli.add_command(pat_group)
cli.add_command(doctor)


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
