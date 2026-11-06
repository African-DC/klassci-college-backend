"""Chaque droit exigé par une route doit exister dans le catalogue semé.

Un droit absent du catalogue n'est attribuable à aucun rôle : la route répond
403 à tout le monde, sans erreur au démarrage ni au déploiement. C'est arrivé
au socle obligatoire de la simulation de grille, gardé par un « fees:read »
que rien ne semait.
"""

from fastapi.routing import APIRoute

from app.main import app
from app.services.tenants.permissions import ALL_PERMISSIONS


def _required_slugs(dependant) -> set[str]:
    slugs: set[str] = set()
    for dep in dependant.dependencies:
        if getattr(dep.call, "__name__", "") == "_check" and dep.call.__closure__:
            slugs |= {
                cell.cell_contents
                for cell in dep.call.__closure__
                if isinstance(cell.cell_contents, str)
            }
        slugs |= _required_slugs(dep)
    return slugs


def test_every_required_permission_is_seeded() -> None:
    seeded = {p["slug"] for p in ALL_PERMISSIONS}
    missing = {
        f"{sorted(route.methods)[0]} {route.path}: {slug}"
        for route in app.routes
        if isinstance(route, APIRoute)
        for slug in _required_slugs(route.dependant)
        if slug not in seeded
    }

    assert not missing, sorted(missing)
