"""``klassci alembic`` — locally-run alembic wrapper (subprocess).

This command is `--local` only by nature: alembic operates on the DB
directly via the alembic CLI installed in the same venv. There is no
HTTP endpoint behind it (alembic shouldn't be exposed over the wire).
"""

import os
import subprocess

import click


@click.group("alembic")
def alembic_group() -> None:
    """Local alembic operations against any tenant DB (subprocess)."""


@alembic_group.command("current")
@click.option("--tenant", "tenant_slug", default="local", show_default=True)
def alembic_current(tenant_slug: str) -> None:
    """Show the current head revision for a tenant DB."""
    _run(["alembic", "current"], tenant_slug)


@alembic_group.command("history")
@click.option("--tenant", "tenant_slug", default="local", show_default=True)
@click.option("--verbose", "-v", is_flag=True)
def alembic_history(tenant_slug: str, verbose: bool) -> None:
    """List the alembic revision history."""
    args = ["alembic", "history"]
    if verbose:
        args.append("-v")
    _run(args, tenant_slug)


@alembic_group.command("upgrade")
@click.argument("revision", default="head")
@click.option("--tenant", "tenant_slug", required=True)
@click.option("--yes", is_flag=True)
def alembic_upgrade(revision: str, tenant_slug: str, yes: bool) -> None:
    """Apply pending migrations on a tenant DB."""
    if not yes and not click.confirm(f"Run alembic upgrade {revision} on tenant '{tenant_slug}'?"):
        click.echo("Annulé.")
        return
    _run(["alembic", "upgrade", revision], tenant_slug)


def _run(args: list[str], tenant_slug: str) -> None:
    env = os.environ.copy()
    env["TENANT_ID"] = tenant_slug
    try:
        result = subprocess.run(args, env=env, capture_output=False, text=True, timeout=300)
    except FileNotFoundError as exc:
        raise click.ClickException(
            "alembic not found in PATH — install it in the active venv."
        ) from exc
    if result.returncode != 0:
        raise click.ClickException(f"alembic exited with code {result.returncode}")
