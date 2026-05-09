"""``klassci doctor`` — platform health summary."""

import asyncio

import click

from app.cli.output import emit


@click.command("doctor")
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Run platform health checks (backend / database / Redis / SMTP)."""
    from app.cli.klassci import get_dispatcher

    dispatcher = get_dispatcher(ctx)
    fmt = ctx.obj["format"]

    async def _run() -> None:
        result = await dispatcher.get("/super-admin/diagnose")
        if fmt == "json":
            emit(result, fmt="json")
        else:
            colour = {"ok": "green", "degraded": "yellow", "down": "red"}.get(
                result["overall"], "white"
            )
            click.secho(f"État global : {result['overall'].upper()}", fg=colour, bold=True)
            click.echo()
            emit(result["checks"], fmt=fmt, columns=["component", "status", "message"])
        await _aclose(dispatcher)

    asyncio.run(_run())


async def _aclose(dispatcher) -> None:
    if hasattr(dispatcher, "aclose"):
        await dispatcher.aclose()
