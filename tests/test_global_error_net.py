"""Filet global — l'imprévu doit rester exploitable depuis l'écran."""

from fastapi.testclient import TestClient

from app.main import app


def _boom() -> None:
    raise RuntimeError("panne simulée")


def test_une_exception_imprevue_devient_du_json_avec_une_reference() -> None:
    """Le texte brut de Starlette n'est pas affichable : le front n'en tire
    qu'une erreur réseau, et personne ne peut relier l'écran au journal."""
    app.add_api_route("/__test_boom", lambda: _boom(), methods=["GET"])
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/__test_boom")

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "INTERNAL"
        assert len(body["reference"]) == 6, "un code court, dictable au telephone"
        assert body["reference"] in body["detail"], "l'utilisateur doit pouvoir le lire"
        assert "panne simulée" not in body["detail"], "aucun detail technique a l'ecran"
    finally:
        app.router.routes = [
            route for route in app.router.routes if getattr(route, "path", "") != "/__test_boom"
        ]


def test_deux_pannes_donnent_deux_references_distinctes() -> None:
    """Une reference partagee ne permettrait pas de retrouver la bonne ligne."""
    app.add_api_route("/__test_boom2", lambda: _boom(), methods=["GET"])
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            first = client.get("/__test_boom2").json()["reference"]
            second = client.get("/__test_boom2").json()["reference"]
        assert first != second
    finally:
        app.router.routes = [
            route for route in app.router.routes if getattr(route, "path", "") != "/__test_boom2"
        ]
