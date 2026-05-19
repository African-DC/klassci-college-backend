"""``klassci pat`` — create / list / revoke personal access tokens."""

import asyncio

import click

from app.cli.output import emit


@click.group("pat")
def pat_group() -> None:
    """Manage personal access tokens for the current user."""


@pat_group.command("list")
@click.pass_context
def list_pats(ctx: click.Context) -> None:
    """List your tokens (no plaintext shown — only metadata)."""
    from app.cli.context import get_dispatcher

    dispatcher = get_dispatcher(ctx)
    fmt = ctx.obj["format"]

    async def _run() -> None:
        result = await dispatcher.get("/super-admin/pats")
        items = result.get("items", [])
        emit(
            items,
            fmt=fmt,
            columns=[
                "id",
                "name",
                "token_prefix",
                "scopes",
                "expires_at",
                "last_used_at",
                "revoked_at",
            ],
        )
        if fmt != "json":
            click.echo(f"\n{result.get('total', len(items))} token(s)")
        await _aclose(dispatcher)

    asyncio.run(_run())


@pat_group.command("create")
@click.option("--name", required=True, help="Human-readable label for the token.")
@click.option(
    "--scope",
    "scopes",
    multiple=True,
    required=True,
    help="Permission slug. Repeat for multiple scopes (e.g. -s super-admin:tenants:read).",
)
@click.option(
    "--expires-in-days",
    type=click.IntRange(1, 365),
    default=90,
    show_default=True,
)
@click.pass_context
def create_pat(
    ctx: click.Context,
    name: str,
    scopes: tuple[str, ...],
    expires_in_days: int,
) -> None:
    """Mint a new token. The plaintext is shown ONCE — copy it immediately."""
    from app.cli.context import get_dispatcher

    dispatcher = get_dispatcher(ctx)
    fmt = ctx.obj["format"]

    payload = {
        "name": name,
        "scopes": list(scopes),
        "expires_in_days": expires_in_days,
    }

    async def _run() -> None:
        result = await dispatcher.post("/super-admin/pats", json_body=payload)
        if fmt == "json":
            emit(result, fmt="json")
        else:
            click.secho(
                "Token créé. Copie-le maintenant — il ne sera plus jamais affiché.", fg="yellow"
            )
            click.echo(f"\n  {result['plaintext']}\n")
            emit(
                {k: v for k, v in result.items() if k != "plaintext"},
                fmt=fmt,
            )
        await _aclose(dispatcher)

    asyncio.run(_run())


@pat_group.command("revoke")
@click.argument("pat_id", type=int)
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def revoke_pat(ctx: click.Context, pat_id: int, yes: bool) -> None:
    """Permanently revoke a token by id. Cannot be undone."""
    from app.cli.context import get_dispatcher

    dispatcher = get_dispatcher(ctx)

    if not yes and not click.confirm(f"Révoquer le token #{pat_id} ?"):
        click.echo("Annulé.")
        return

    async def _run() -> None:
        await dispatcher.delete(f"/super-admin/pats/{pat_id}")
        click.secho(f"Token #{pat_id} révoqué.", fg="green")
        await _aclose(dispatcher)

    asyncio.run(_run())


async def _aclose(dispatcher) -> None:
    if hasattr(dispatcher, "aclose"):
        await dispatcher.aclose()
