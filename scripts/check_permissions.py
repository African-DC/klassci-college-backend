#!/usr/bin/env python3
"""Un acces se demande a la matrice des droits. Il ne se deduit pas d'un role.

Ce que ce controle garde, et pourquoi il existe
==============================================

Une ecole repartit ses postes comme elle veut. Celle-ci confie la caisse au
secretariat, celle-la a un comptable ; une troisieme donnera la configuration
des annees a sa directrice des etudes. La matrice des droits existe pour que ce
choix soit le sien, et qu'il se fasse sans toucher au code.

Chaque fois qu'un acces se lit `if role == "admin"`, cette promesse tombe :
donner la permission a quelqu'un d'autre ne suffit plus, et personne ne pense a
revenir modifier la ligne. L'ecran reste vide pour la personne qui en a
desormais la charge, et ouvert pour celle a qui on l'a retiree.

Ce que ce controle **ne peut pas** faire
========================================

Il ne verifie pas qu'une route demande le **bon** droit. Rien ici ne sait que
le tableau des soldes releve de `payments:read:all` et non de `payments:read` —
c'est un jugement, il se prend en revue. Le controle garantit qu'un droit est
demande, pas qu'il est le bon.

Il ne voit pas non plus si un bouton est affiche a qui ne peut pas s'en servir.
C'est du rendu, et le rendu se regarde a l'ecran.

Dire ce qu'il ne couvre pas fait partie de son travail : un garde-fou qu'on
croit total est plus dangereux que pas de garde-fou du tout.

    python scripts/check_permissions.py            # tout le depot
    python scripts/check_permissions.py --staged   # seulement ce qui est indexe
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Regle 1 — toute route est gardee
# ---------------------------------------------------------------------------

_ROUTE = re.compile(r"@router\.(get|post|put|patch|delete)\(")
_GARDE = re.compile(
    r"require_permission|require_any_permission|has_permission"
    r"|get_current_user|require_super_admin"
)
_NOM = re.compile(r"async def (\w+)")

#: Les seules routes que personne n'a besoin d'etre pour appeler, et la raison.
#:
#: Cette liste est de la documentation autant qu'une exception : elle repond a
#: « qu'est-ce qui est ouvert sur cette API », question qu'on ne devrait jamais
#: avoir a reconstituer en lisant trois cents signatures.
ROUTES_PUBLIQUES: dict[str, str] = {
    "app/routers/auth.py::login": "on ne peut pas exiger une session pour en ouvrir une",
    "app/routers/auth.py::refresh": "porte le cookie de rafraichissement, pas un jeton",
    "app/routers/mailpulse_public.py::inbound_message": "webhook entrant, signe par le fournisseur",
    "app/routers/public_verify.py::verify_by_token": "verification d'un document par un tiers",
    "app/routers/public_verify.py::verify_by_seal_code": "verification d'un document par un tiers",
    "app/routers/public_verify.py::verify_file_by_token": "verification d'un fichier par un tiers",
    "app/routers/public_verify.py::verify_file_by_code": "verification d'un fichier par un tiers",
    "app/routers/public_upload_handoff.py::describe_handoff": (
        "page de depot ouverte en scannant un code 2D, sur un telephone sans session ; "
        "ne rend qu'un libelle discret (prenom et initiale) et le nom de l'etablissement"
    ),
    "app/routers/public_upload_handoff.py::deposit_handoff": (
        "depot d'une photo depuis un telephone sans session ; n'ecrit AUCUNE fiche, "
        "seulement un fichier dans le sas, et c'est l'operateur authentifie qui confirme"
    ),
}

# ---------------------------------------------------------------------------
# Regle 2 — aucun role ne decide d'un acces
# ---------------------------------------------------------------------------

_ROLE = re.compile(r"""\.role\s*(?:==|!=)|\.role\s+(?:not\s+)?in\s""")

#: Les couches ou un role decide d'un acces. Ailleurs — depots, services de
#: profil — comparer un role sert a choisir la bonne table, pas a autoriser :
#: `admin` lit un profil administratif, `teacher` un profil enseignant. C'est
#: du polymorphisme, et l'interdire noierait ce controle de faux positifs
#: jusqu'a ce que quelqu'un le desactive.
COUCHES_D_ACCES = ("app/routers/", "app/core/dependencies.py", "app/core/middleware.py")


@dataclass(frozen=True)
class Faute:
    fichier: str
    ligne: int
    regle: str
    quoi: str
    pourquoi: str


def _fichiers(staged: bool) -> list[Path]:
    if not staged:
        return sorted(p for p in (RACINE / "app").rglob("*.py"))
    sortie = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=RACINE,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [
        RACINE / nom
        for nom in sortie.split()
        if nom.startswith("app/") and nom.endswith(".py") and (RACINE / nom).exists()
    ]


def _routes_nues(chemin: Path, src: str) -> list[Faute]:
    relatif = chemin.relative_to(RACINE).as_posix()
    fautes: list[Faute] = []
    morceaux = re.split(r"(?=@router\.(?:get|post|put|patch|delete)\()", src)
    ligne_courante = src[: src.find(morceaux[1])].count("\n") + 1 if len(morceaux) > 1 else 0

    for morceau in morceaux[1:]:
        nom = _NOM.search(morceau)
        cle = f"{relatif}::{nom.group(1) if nom else '?'}"
        # La signature s'arrete au corps : une garde citee dans une docstring
        # ne garde rien.
        fin = morceau.find('"""')
        signature = morceau[: fin if fin > 0 else min(len(morceau), 900)]
        if not _GARDE.search(signature) and cle not in ROUTES_PUBLIQUES:
            fautes.append(
                Faute(
                    fichier=relatif,
                    ligne=ligne_courante,
                    regle="route sans garde",
                    quoi=cle,
                    pourquoi=(
                        'Ajoutez `require_permission("...")`, ou declarez la route dans '
                        "ROUTES_PUBLIQUES avec la raison qui la rend ouverte."
                    ),
                )
            )
        ligne_courante += morceau.count("\n")
    return fautes


def _roles_qui_autorisent(chemin: Path, src: str) -> list[Faute]:
    relatif = chemin.relative_to(RACINE).as_posix()
    if not any(relatif.startswith(c) or relatif == c for c in COUCHES_D_ACCES):
        return []
    fautes = []
    for numero, ligne in enumerate(src.splitlines(), 1):
        nu = ligne.strip()
        if nu.startswith("#") or not _ROLE.search(ligne):
            continue
        fautes.append(
            Faute(
                fichier=relatif,
                ligne=numero,
                regle="role qui autorise",
                quoi=nu[:90],
                pourquoi=(
                    'Un acces se demande a la matrice : `require_permission("...")`. '
                    "Une ecole qui confie ce poste a un autre role doit pouvoir le faire "
                    "sans toucher au code."
                ),
            )
        )
    return fautes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Ne lire que les fichiers indexes.")
    args = parser.parse_args()

    fautes: list[Faute] = []
    for chemin in _fichiers(args.staged):
        src = chemin.read_text(encoding="utf-8")
        if "app/routers/" in chemin.as_posix():
            fautes.extend(_routes_nues(chemin, src))
        fautes.extend(_roles_qui_autorisent(chemin, src))

    if not fautes:
        print("Permissions : rien a signaler.")
        return 0

    print("\nUn acces se demande a la matrice des droits, il ne se deduit pas d'un role.\n")
    for f in fautes:
        print(f"  {f.fichier}:{f.ligne}  [{f.regle}]")
        print(f"      {f.quoi}")
        print(f"      {f.pourquoi}\n")
    print(f"{len(fautes)} a corriger. Detail de la regle : scripts/check_permissions.py\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
