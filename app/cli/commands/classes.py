"""``klassci class`` — list classes of a tenant."""

import asyncio

import click

from app.cli.output import emit


@click.group("class")
def class_group() -> None:
    """Browse classes of a specific tenant."""


@class_group.command("list")
@click.option("--tenant", "tenant_slug", required=True, help="Target tenant slug.")
@click.option("--limit", default=50, type=click.IntRange(1, 500), show_default=True)
@click.option("--offset", default=0, type=click.IntRange(0), show_default=True)
@click.pass_context
def list_classes(ctx: click.Context, tenant_slug: str, limit: int, offset: int) -> None:
    """List classes (paginated)."""
    from app.cli.klassci import get_dispatcher

    dispatcher = get_dispatcher(ctx)
    fmt = ctx.obj["format"]

    async def _run() -> None:
        result = await dispatcher.get(
            f"/super-admin/tenants/{tenant_slug}/classes", limit=limit, offset=offset
        )
        items = result.get("items", [])
        emit(
            items,
            fmt=fmt,
            columns=["id", "name", "code", "level_id", "series_id", "max_capacity"],
        )
        if fmt != "json":
            click.echo(f"\n{len(items)} of {result.get('total', '?')} (offset={offset})")
        if hasattr(dispatcher, "aclose"):
            await dispatcher.aclose()

    asyncio.run(_run())
