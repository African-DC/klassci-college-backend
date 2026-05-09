"""``klassci db`` — raw SQL execution against any tenant DB (risky)."""

import asyncio

import click

from app.cli.output import emit


@click.group("db")
def db_group() -> None:
    """Raw SQL operations. Always preview with --dry-run first."""


@db_group.command("query")
@click.argument("sql")
@click.option("--tenant", "tenant_slug", required=True, help="Target tenant DB.")
@click.option("--execute", is_flag=True, help="Actually run the SQL (default = dry-run).")
@click.option("--limit", default=1000, type=click.IntRange(1, 10_000), show_default=True)
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt when --execute is on.")
@click.pass_context
def db_query(
    ctx: click.Context,
    sql: str,
    tenant_slug: str,
    execute: bool,
    limit: int,
    yes: bool,
) -> None:
    """Run a SQL query. Without --execute you get warnings only (preview)."""
    from app.cli.klassci import get_dispatcher

    dispatcher = get_dispatcher(ctx)
    fmt = ctx.obj["format"]
    dry_run = not execute

    if execute and not yes:
        click.secho(f"\n  TENANT : {tenant_slug}", fg="cyan")
        click.secho(f"  SQL    : {sql}\n", fg="cyan")
        if not click.confirm("Exécuter cette requête ?"):
            click.echo("Annulé.")
            return

    payload = {
        "tenant_slug": tenant_slug,
        "sql": sql,
        "dry_run": dry_run,
        "limit": limit,
    }

    async def _run() -> None:
        result = await dispatcher.post("/super-admin/db/query", json_body=payload)
        if fmt == "json":
            emit(result, fmt="json")
        else:
            for warning in result.get("warnings", []):
                colour = {"danger": "red", "warning": "yellow", "info": "blue"}.get(
                    warning["severity"], "white"
                )
                click.secho(f"[{warning['severity']}] {warning['message']}", fg=colour)
            if result["dry_run"]:
                click.secho("\nDry-run — aucune requête exécutée.", fg="yellow")
                return
            click.echo(f"\n{result['rowcount']} ligne(s) en {result.get('elapsed_ms', 0):.1f} ms")
            if result.get("rows"):
                rows_as_dicts = [
                    dict(zip(result["columns"], row, strict=False)) for row in result["rows"]
                ]
                emit(rows_as_dicts, fmt="human", columns=result["columns"])
            if result.get("truncated"):
                click.secho(f"[result truncated to {limit} rows]", fg="yellow")
        if hasattr(dispatcher, "aclose"):
            await dispatcher.aclose()

    asyncio.run(_run())
