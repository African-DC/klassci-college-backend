"""KLASSCI Collège — Backend API.

Point d'entrée de l'application FastAPI.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.middleware import TenantMiddleware
from app.routers.auth import router as auth_router

app = FastAPI(
    title=settings.APP_NAME,
    description="API de gestion scolaire multi-tenant",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# --- Middleware (ordre : dernier ajouté = premier exécuté) ---
# TenantMiddleware ajouté en 1er → s'exécute en dernier (inner layer)
# CORSMiddleware ajouté en 2ème → s'exécute en premier (outer layer)
# Ainsi les preflight CORS sont traités avant la résolution tenant.
app.add_middleware(TenantMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Handlers d'exception ---
register_exception_handlers(app)

# --- Routers ---
app.include_router(auth_router)


# ---------------------------------------------------------------------------
# Routes de base
# ---------------------------------------------------------------------------


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Vérification de santé — utilisé par le CI et le load balancer."""
    return {"status": "ok"}
