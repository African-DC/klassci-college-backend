"""CLI output formatting: human / json / table."""

import json
import sys
from typing import Any

import click
from tabulate import tabulate

OUTPUT_FORMATS = ("human", "json", "table")


def format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def emit(data: Any, fmt: str = "human", *, columns: list[str] | None = None) -> None:
    """Print `data` in the requested format.

    `data` is one of:
      - dict — single record
      - list[dict] — collection
      - str — message
    `columns` constrains which keys are shown for table/human modes.
    """
    if fmt == "json":
        json.dump(data, sys.stdout, indent=2, ensure_ascii=False, default=str)
        click.echo()
        return

    if isinstance(data, str):
        click.echo(data)
        return

    if isinstance(data, list):
        if not data:
            click.echo("(aucun résultat)")
            return
        cols = columns or list(data[0].keys())
        rows = [[format_value(row.get(c)) for c in cols] for row in data]
        click.echo(tabulate(rows, headers=cols, tablefmt="rounded_outline"))
        return

    if isinstance(data, dict):
        cols = columns or list(data.keys())
        rows = [[c, format_value(data.get(c))] for c in cols]
        click.echo(tabulate(rows, headers=("champ", "valeur"), tablefmt="rounded_outline"))
        return

    click.echo(str(data))
