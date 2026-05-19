"""``klassci`` — KLASSCI College admin CLI.

Invoke via ``python -m app.cli.klassci`` (a console_scripts entry point
will land once the project ships a ``[project]`` section in pyproject).

``get_dispatcher`` lives in ``app.cli.context`` to break the cyclic
import that arose when command modules needed to access the dispatcher
defined alongside the root group.
"""

from __future__ import annotations

import os

import click

from app.cli.commands.alembic_cmd import alembic_group
from app.cli.commands.classes import class_group
from app.cli.commands.db import db_group
from app.cli.commands.doctor import doctor
from app.cli.commands.login import login
from app.cli.commands.logs import logs
from app.cli.commands.pat import pat_group
from app.cli.commands.student import student_group
from app.cli.commands.teacher import teacher_group
from app.cli.commands.tenant import tenant_group
from app.cli.context import get_dispatcher  # noqa: F401  re-export for backward compat

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


cli.add_command(login)
cli.add_command(tenant_group)
cli.add_command(student_group)
cli.add_command(teacher_group)
cli.add_command(class_group)
cli.add_command(pat_group)
cli.add_command(doctor)
cli.add_command(logs)
cli.add_command(db_group)
cli.add_command(alembic_group)


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
