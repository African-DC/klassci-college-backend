"""``klassci logs`` — read system logs (with redaction)."""

import asyncio

import click

from app.cli.output import emit


@click.command("logs")
@click.option("--service", default="klassci-backend", help="systemd unit name.")
@click.option("--lines", "-n", default=200, type=click.IntRange(1, 5000), show_default=True)
@click.pass_context
def logs(ctx: click.Context, service: str, lines: int) -> None:
    """Tail journalctl for a service. Auth headers / tokens / emails are redacted."""
    from app.cli.context import get_dispatcher

    dispatcher = get_dispatcher(ctx)
    fmt = ctx.obj["format"]

    async def _run() -> None:
        result = await dispatcher.get("/super-admin/logs", service=service, lines=lines)
        if fmt == "json":
            emit(result, fmt="json")
        else:
            click.secho(
                f"Service: {result['service']}  ({result['redacted_count']} redactions)",
                fg="cyan",
            )
            for entry in result["lines"]:
                click.echo(entry["raw"])
            if result["truncated"]:
                click.secho("[output truncated]", fg="yellow")
        if hasattr(dispatcher, "aclose"):
            await dispatcher.aclose()

    asyncio.run(_run())
