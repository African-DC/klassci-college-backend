"""Router Super Admin — provisioning de tenants via API."""

from fastapi import APIRouter, Depends

from app.core.dependencies import TokenData, get_current_user, require_permission
from app.schemas.tenant import TenantProvisionRequest, TenantProvisionResponse
from app.services import tenant_service

router = APIRouter(prefix="/super-admin", tags=["super-admin"])


@router.post("/tenants", response_model=TenantProvisionResponse, status_code=201)
async def provision_tenant(
    data: TenantProvisionRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("super-admin:tenants:create"),
) -> TenantProvisionResponse:
    """Provisionne un nouveau tenant : crée la DB, migre, et seed les données initiales."""
    result = await tenant_service.provision_tenant(
        tenant_slug=data.tenant_slug,
        school_name=data.school_name,
        admin_email=data.admin_email,
        admin_password=data.admin_password,
        school_address=data.school_address,
        school_phone=data.school_phone,
        school_email=data.school_email,
        ministry_code=data.ministry_code,
    )
    return TenantProvisionResponse(
        tenant_slug=result["tenant_slug"],
        database=result["database"],
        admin_email=result["admin_email"],
        status=result["status"],
        url=f"https://{result['tenant_slug']}.klassci.com",
    )
