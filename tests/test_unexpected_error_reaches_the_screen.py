"""Une panne imprévue doit arriver jusqu'à l'écran, pas mourir dans le navigateur.

Le dispositif a une seule raison d'être : donner à l'utilisateur un code de
référence qu'il puisse recopier. Si la réponse sort sans en-tête CORS, le
navigateur la bloque, l'utilisateur voit une erreur réseau, et le code ne lui
parvient jamais. Un `@app.exception_handler(Exception)` seul produit exactement
ce cas : Starlette confie cette clé à `ServerErrorMiddleware`, qui coiffe la
pile CORS comprise.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.exceptions import UnexpectedErrorMiddleware, register_exception_handlers

ORIGINE = "http://ecole.test"


def _app() -> FastAPI:
    """Reproduit l'ordre des middlewares de `app/main.py`."""
    app = FastAPI()
    app.add_middleware(UnexpectedErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ORIGINE],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    @app.get("/panne")
    def panne() -> None:
        raise RuntimeError("panne simulée")

    @app.get("/normal")
    def normal() -> dict[str, str]:
        return {"etat": "bien"}

    return app


def _client() -> TestClient:
    return TestClient(_app(), raise_server_exceptions=False)


def test_le_500_porte_les_entetes_cors(caplog) -> None:
    with caplog.at_level(logging.CRITICAL):
        reponse = _client().get("/panne", headers={"Origin": ORIGINE})

    assert reponse.status_code == 500
    # Sans cet en-tête, le navigateur jette la réponse et l'utilisateur ne voit
    # qu'une erreur réseau.
    assert reponse.headers.get("access-control-allow-origin") == ORIGINE


def test_le_500_rend_un_code_de_reference_recopiable(caplog) -> None:
    with caplog.at_level(logging.CRITICAL):
        corps = _client().get("/panne", headers={"Origin": ORIGINE}).json()

    assert corps["code"] == "INTERNAL"
    assert len(corps["reference"]) == 6
    assert corps["reference"] in corps["detail"]
    # Hexadécimal en capitales : dictable au téléphone sans ambiguïté de casse.
    assert set(corps["reference"]) <= set("0123456789ABCDEF")


def test_une_reponse_normale_reste_intacte() -> None:
    reponse = _client().get("/normal", headers={"Origin": ORIGINE})

    assert reponse.status_code == 200
    assert reponse.json() == {"etat": "bien"}
    assert reponse.headers.get("access-control-allow-origin") == ORIGINE
