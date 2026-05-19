"""Platform diagnostics endpoint — backend / DB / Redis / SMTP liveness."""

from fastapi import APIRouter

from app.core.dependencies import require_permission
from app.schemas.diagnose import PlatformHealth
from app.services.diagnose_service import collect_platform_health

router = APIRouter(prefix="/diagnose", tags=["super-admin"])


@router.get(
    "",
    response_model=PlatformHealth,
    summary="Platform health: backend, database, Redis, SMTP",
)
async def get_platform_health(
    _: None = require_permission("super-admin:diagnose:read"),
) -> PlatformHealth:
    payload = await collect_platform_health()
    return PlatformHealth.model_validate(payload)
