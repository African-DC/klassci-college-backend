"""Point d'entrée en ligne de commande du jeu de données de démonstration."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.cli.seed_demo.report import render
from app.cli.seed_demo.runner import STEP_NAMES, seed


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.seed_demo",
        description=(
            "Peuple un locataire KLASSCI avec une année scolaire complète de "
            "collège-lycée privé ivoirien. Additif et relançable : ne duplique "
            "rien, ne supprime rien, ne vide aucune table."
        ),
    )
    parser.add_argument("--tenant", required=True, help="Slug du locataire (nom de la base)")
    parser.add_argument(
        "--only",
        action="append",
        choices=STEP_NAMES,
        help=(
            "Ne rejoue que cette étape (répétable). Le référentiel tourne "
            "toujours, il fournit les identifiants aux autres."
        ),
    )
    parser.add_argument("--quiet", action="store_true", help="N'affiche que le récapitulatif final")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("klassci.seed").setLevel(logging.INFO)

    try:
        values = asyncio.run(seed(args.tenant, only=tuple(args.only or ())))
    except Exception as error:  # noqa: BLE001, le message importe plus que la trace
        logging.getLogger("klassci.seed").exception("Semis interrompu")
        print(f"\nSemis interrompu : {error}", file=sys.stderr)
        return 1

    print(f"\nLocataire « {args.tenant} » : état après semis :")
    print(render(values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
