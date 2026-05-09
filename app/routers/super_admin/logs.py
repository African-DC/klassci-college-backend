"""journalctl proxy with redaction. Risky endpoint (Path F)."""

from fastapi import APIRouter, HTTPException, Query

from app.core.dependencies import require_permission
from app.schemas.logs import LogLine, LogsResponse
from app.services.logs_service import MAX_LINES, is_valid_service_name, read_journalctl

router = APIRouter(prefix="/logs", tags=["super-admin"])


@router.get(
    "",
    response_model=LogsResponse,
    summary="Read systemd journal lines for a service (with redaction)",
)
async def get_logs(
    service: str = Query("klassci-backend", description="systemd unit name"),
    lines: int = Query(200, ge=1, le=MAX_LINES),
    _: None = require_permission("super-admin:logs:read"),
) -> LogsResponse:
    if not is_valid_service_name(service):
        raise HTTPException(status_code=400, detail="Invalid service name")

    try:
        result = read_journalctl(service, lines)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return LogsResponse(
        service=service,
        lines=[LogLine(raw=ln) for ln in result.lines],
        truncated=result.truncated,
        redacted_count=result.redacted_count,
    )
