"""L'ordre des routes ne doit pas tenir qu'à une position dans une liste.

`/admin/students/doublons` ne se résout avant `/admin/students/{student_id}`
que parce que son routeur est monté en premier dans `main.py`, hors du bloc
autrement trié. Quelqu'un qui remet cette liste en ordre alphabétique obtient
un 422 à chaque touche du formulaire, sans qu'aucun test ne bouge.
"""

from fastapi.routing import APIRoute

from app.main import app


def _index(chemin: str) -> int:
    for i, route in enumerate(app.routes):
        if isinstance(route, APIRoute) and route.path == chemin:
            return i
    raise AssertionError(f"route absente : {chemin}")


def test_la_route_litterale_se_resout_avant_la_parametrique() -> None:
    litterale = _index("/admin/students/doublons")
    parametrique = _index("/admin/students/{student_id}")
    assert litterale < parametrique, (
        "FastAPI essaie les routes dans l'ordre d'enregistrement : "
        "`/students/doublons` doit précéder `/students/{student_id}`, "
        "sinon il tente int('doublons') et rend 422."
    )
