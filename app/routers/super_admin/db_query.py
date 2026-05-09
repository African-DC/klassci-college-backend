"""Raw SQL execution endpoint. Risky by design (Path F).

Always preview with ``dry_run=true`` first. Every execution is audit-logged.
Body validation rejects multi-statement queries and caps row count.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import TokenData, get_current_user, require_permission
from app.schemas.db_query import DBQueryRequest, DBQueryResponse, DBQueryWarning
from app.services.db_query_service import analyse_sql, execute_sql

router = APIRouter(prefix="/db", tags=["super-admin"])
logger = logging.getLogger("klassci.audit")


@router.post(
    "/query",
    response_model=DBQueryResponse,
    summary="Execute a raw SQL query against a tenant DB (preview or execute)",
)
async def run_query(
    data: DBQueryRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("super-admin:db:execute"),
) -> DBQueryResponse:
    warnings_data = analyse_sql(data.sql)
    warnings = [DBQueryWarning(**w) for w in warnings_data]

    if data.dry_run:
        return DBQueryResponse(
            tenant_slug=data.tenant_slug,
            dry_run=True,
            warnings=warnings,
        )

    logger.warning(
        "DB QUERY EXECUTE user=%s tenant=%s sql=%r",
        current_user.email,
        data.tenant_slug,
        data.sql[:500],
    )
    try:
        outcome = await execute_sql(data.tenant_slug, data.sql, limit=data.limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DBQueryResponse(
        tenant_slug=data.tenant_slug,
        dry_run=False,
        warnings=warnings,
        rowcount=outcome["rowcount"],
        columns=outcome["columns"],
        rows=outcome["rows"],
        elapsed_ms=outcome["elapsed_ms"],
        truncated=outcome["truncated"],
    )
