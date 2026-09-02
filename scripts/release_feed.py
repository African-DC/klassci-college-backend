#!/usr/bin/env python3
"""Transforme `CHANGELOG.md` en un flux lisible par une machine.

Le changelog est ecrit pour un humain, et il doit le rester : c'est ce qui le
rend utile en revue. Mais la page vitrine et son agent ont besoin de la meme
matiere sous une forme qu'on ne devine pas — sans quoi chacun ecrira son propre
analyseur de Markdown, et les deux dériveront du fichier le jour ou une entree
sortira du gabarit.

Une seule source, donc, et une projection. Le fichier reste la verite ; ce
flux n'est qu'une vue, regeneree a chaque poussee sur `main`.

Ce que la projection sait lire, parce que la regle du depot l'impose deja
(`.claude/rules/changelog.md`) :

- les sections Keep a Changelog (`### Added`, `### Fixed`, ...) ;
- le persona en italique en fin de ligne — `*(admin, comptable)*` — qui devient
  une liste, de quoi filtrer « ce qui a change pour un parent » ;
- le numero de PR entre parentheses — `(#42)` — qui devient un lien.

Ce qu'elle ne fait pas : deviner. Une ligne qui ne porte ni persona ni PR sort
avec des champs vides, jamais avec une valeur inventee.

    python scripts/release_feed.py            # ecrit RELEASES.json
    python scripts/release_feed.py --check    # echoue si le fichier a derive
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CHANGELOG = RACINE / "CHANGELOG.md"
SORTIE = RACINE / "RELEASES.json"

#: `## [0.1.0] - 2026-09-02` ou `## [Unreleased]`
_VERSION = re.compile(r"^##\s+\[([^\]]+)\]\s*(?:-\s*(\d{4}-\d{2}-\d{2}))?\s*$")
#: `### Added`
_SECTION = re.compile(r"^###\s+(.+?)\s*$")
#: `- Ce que l'utilisateur peut faire *(admin, parent)* (#42)`
_ENTREE = re.compile(r"^-\s+(.*)$")
_PERSONA = re.compile(r"\*\(([^)]+)\)\*")
_PR = re.compile(r"\(#(\d+)\)")


@dataclass
class Entree:
    """Une ligne du changelog, telle qu'un ecran peut la consommer."""

    text: str
    #: Les personas nommes en italique. Vide quand la ligne est transverse.
    audience: list[str] = field(default_factory=list)
    #: Le numero de PR, quand la ligne en porte un. `None` sinon, jamais 0.
    pull_request: int | None = None


@dataclass
class Version:
    version: str
    #: `None` pour `Unreleased` : elle n'a pas de date tant qu'elle n'est pas
    #: taguee, et en inventer une ferait croire a une livraison.
    date: str | None
    released: bool
    sections: dict[str, list[Entree]] = field(default_factory=dict)


def _lire_entree(ligne: str) -> Entree:
    """Extrait le persona et la PR sans les retirer du texte lisible."""
    personas = _PERSONA.search(ligne)
    pr = _PR.search(ligne)

    texte = ligne
    if personas:
        texte = texte.replace(personas.group(0), "")
    if pr:
        texte = texte.replace(pr.group(0), "")

    return Entree(
        text=" ".join(texte.split()).rstrip(" ,;"),
        audience=[p.strip() for p in personas.group(1).split(",")] if personas else [],
        pull_request=int(pr.group(1)) if pr else None,
    )


def analyser(markdown: str) -> list[Version]:
    """Lit le changelog section par section, sans rien deviner."""
    versions: list[Version] = []
    section_courante: str | None = None

    for ligne in markdown.splitlines():
        entete = _VERSION.match(ligne)
        if entete:
            nom, date = entete.group(1), entete.group(2)
            versions.append(
                Version(
                    version=nom,
                    date=date,
                    released=nom.lower() != "unreleased" and date is not None,
                )
            )
            section_courante = None
            continue

        if not versions:
            # Tout ce qui precede la premiere version est le preambule du
            # fichier : il explique le format, il ne decrit aucune livraison.
            continue

        section = _SECTION.match(ligne)
        if section:
            section_courante = section.group(1)
            versions[-1].sections.setdefault(section_courante, [])
            continue

        entree = _ENTREE.match(ligne.strip())
        if entree and section_courante:
            # Les liens de comparaison en bas de fichier commencent aussi par
            # un tiret ; ils n'appartiennent a aucune section.
            versions[-1].sections[section_courante].append(_lire_entree(entree.group(1)))

    return versions


def construire(produit: str) -> dict[str, object]:
    versions = analyser(CHANGELOG.read_text(encoding="utf-8"))
    livrees = [v for v in versions if v.released]
    return {
        "product": produit,
        "source": "CHANGELOG.md",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "current_version": livrees[0].version if livrees else None,
        "versions": [asdict(v) for v in versions],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="N'ecrit rien ; echoue si RELEASES.json ne correspond plus au changelog.",
    )
    parser.add_argument("--product", default=RACINE.name)
    args = parser.parse_args()

    flux = construire(args.product)
    rendu = json.dumps(flux, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        if not SORTIE.exists():
            print(f"{SORTIE.name} manque. Lancez : python scripts/release_feed.py", file=sys.stderr)
            return 1
        # `generated_at` bouge a chaque execution : le comparer ferait echouer
        # une verification sur une horloge, pas sur un contenu.
        avant = json.loads(SORTIE.read_text(encoding="utf-8"))
        avant.pop("generated_at", None)
        apres = json.loads(rendu)
        apres.pop("generated_at", None)
        if avant != apres:
            print(
                f"{SORTIE.name} a derive du changelog. Lancez : python scripts/release_feed.py",
                file=sys.stderr,
            )
            return 1
        return 0

    SORTIE.write_text(rendu, encoding="utf-8")
    entrees = sum(len(s) for v in flux["versions"] for s in v["sections"].values())  # type: ignore[index,union-attr]
    print(f"{SORTIE.name} : {len(flux['versions'])} versions, {entrees} entrees.")  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
