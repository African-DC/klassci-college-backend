"""``klassci tenant`` — provision / list / show / check-slug."""

import asyncio
import getpass

import click

from app.cli.output import emit


@click.group("tenant")
def tenant_group() -> None:
    """Manage tenants (schools)."""


@tenant_group.command("list")
@click.pass_context
def list_tenants(ctx: click.Context) -> None:
    """List all tenants on the platform."""
    from app.cli.klassci import get_dispatcher

    dispatcher = get_dispatcher(ctx)
    fmt = ctx.obj["format"]

    async def _run() -> None:
        result = await dispatcher.get("/super-admin/tenants")
        items = result.get("items", [])
        emit(items, fmt=fmt, columns=["slug", "url", "db_size_bytes"])
        if fmt != "json":
            click.echo(f"\n{result.get('total', len(items))} tenant(s)")
        await _aclose(dispatcher)

    asyncio.run(_run())


@tenant_group.command("show")
@click.argument("slug")
@click.pass_context
def show_tenant(ctx: click.Context, slug: str) -> None:
    """Show details and stats for a single tenant."""
    from app.cli.klassci import get_dispatcher

    dispatcher = get_dispatcher(ctx)
    fmt = ctx.obj["format"]

    async def _run() -> None:
        result = await dispatcher.get(f"/super-admin/tenants/{slug}")
        if fmt == "json":
            emit(result, fmt="json")
        else:
            emit(
                {
                    "slug": result["slug"],
                    "url": result["url"],
                    "alembic_head": result.get("alembic_head"),
                    "db_size_bytes": result["db_size_bytes"],
                    **{f"count.{k}": v for k, v in result["counts"].items()},
                },
                fmt=fmt,
            )
        await _aclose(dispatcher)

    asyncio.run(_run())


@tenant_group.command("check-slug")
@click.argument("slug")
@click.pass_context
def check_slug(ctx: click.Context, slug: str) -> None:
    """Check whether a slug is valid and available."""
    from app.cli.klassci import get_dispatcher

    dispatcher = get_dispatcher(ctx)
    fmt = ctx.obj["format"]

    async def _run() -> None:
        result = await dispatcher.post("/super-admin/tenants/check-slug", json_body={"slug": slug})
        emit(result, fmt=fmt)
        await _aclose(dispatcher)

    asyncio.run(_run())


@tenant_group.command("create")
@click.option("--slug", required=True)
@click.option("--name", "school_name", required=True)
@click.option("--admin-email", required=True)
@click.option(
    "--admin-password",
    default=None,
    help="If omitted, prompts (input hidden).",
)
@click.option("--address", default=None)
@click.option("--phone", default=None)
@click.option("--school-email", default=None)
@click.option("--ministry-code", default=None)
@click.pass_context
def create_tenant(
    ctx: click.Context,
    slug: str,
    school_name: str,
    admin_email: str,
    admin_password: str | None,
    address: str | None,
    phone: str | None,
    school_email: str | None,
    ministry_code: str | None,
) -> None:
    """Provision a new tenant (creates DB, runs migrations, seeds admin)."""
    from app.cli.klassci import get_dispatcher

    dispatcher = get_dispatcher(ctx)
    fmt = ctx.obj["format"]

    if not admin_password:
        admin_password = getpass.getpass("Mot de passe admin (min 8 car.) : ")

    payload = {
        "tenant_slug": slug,
        "school_name": school_name,
        "admin_email": admin_email,
        "admin_password": admin_password,
        "school_address": address,
        "school_phone": phone,
        "school_email": school_email,
        "ministry_code": ministry_code,
    }

    async def _run() -> None:
        result = await dispatcher.post("/super-admin/tenants", json_body=payload)
        emit(result, fmt=fmt)
        if fmt != "json":
            click.secho(f"\nTenant '{result['tenant_slug']}' provisionné.", fg="green")
            click.echo(f"  URL : {result['url']}")
        await _aclose(dispatcher)

    asyncio.run(_run())


async def _aclose(dispatcher) -> None:
    if hasattr(dispatcher, "aclose"):
        await dispatcher.aclose()
