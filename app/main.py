"""
KLASSCI Collège — Backend API

Point d'entrée de l'application FastAPI.
À compléter selon l'issue #1 (feat/core-bootstrap).
"""
from fastapi import FastAPI

app = FastAPI(
    title="KLASSCI Collège API",
    description="API de gestion scolaire multi-tenant",
    version="1.0.0",
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Vérification de santé — utilisé par le CI et le load balancer."""
    return {"status": "ok"}
