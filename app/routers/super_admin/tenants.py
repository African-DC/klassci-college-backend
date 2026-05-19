"""Super-admin tenant ops: provision, list, show, slug availability check."""

from fastapi import APIRouter, HTTPException

from app.core.dependencies import require_permission
from app.core.slug import is_reserved_tenant_slug, is_valid_tenant_slug
from app.schemas.tenant import (
    SlugCheckRequest,
    SlugCheckResponse,
    TenantDetailResponse,
    TenantListItem,
    TenantListResponse,
    TenantProvisionRequest,
    TenantProvisionResponse,
    to_detail_response,
)
from app.services.tenants import (
    TenantAlreadyProvisioned,
    get_tenant_summary,
    get_tenants_overview,
    provision_tenant,
    slug_exists,
)

router = APIRouter(prefix="/tenants", tags=["super-admin"])


@router.post(
    "",
    response_model=TenantProvisionResponse,
    status_code=201,
    summary="Provision a new tenant",
)
async def create_tenant(
    data: TenantProvisionRequest,
    _: None = require_permission("super-admin:tenants:create"),
) -> TenantProvisionResponse:
    try:
        result = await provision_tenant(
            tenant_slug=data.tenant_slug,
            school_name=data.school_name,
            admin_email=data.admin_email,
            admin_password=data.admin_password,
            school_address=data.school_address,
            school_phone=data.school_phone,
            school_email=data.school_email,
            ministry_code=data.ministry_code,
        )
    except TenantAlreadyProvisioned as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return TenantProvisionResponse(
        tenant_slug=result["tenant_slug"],
        database=result["database"],
        admin_email=result["admin_email"],
        status=result["status"],
        url=result["tenant_url"],
    )


@router.get(
    "",
    response_model=TenantListResponse,
    summary="List all tenants on the platform",
)
async def list_tenants(
    _: None = require_permission("super-admin:tenants:read"),
) -> TenantListResponse:
    overview = await get_tenants_overview()
    items = [TenantListItem(**row) for row in overview]
    return TenantListResponse(items=items, total=len(items))


@router.get(
    "/{slug}",
    response_model=TenantDetailResponse,
    summary="Get tenant detail and stats",
)
async def get_tenant(
    slug: str,
    _: None = require_permission("super-admin:tenants:read"),
) -> TenantDetailResponse:
    if not is_valid_tenant_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid slug format")
    summary = await get_tenant_summary(slug)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"Tenant '{slug}' not found")
    return to_detail_response(summary)


@router.post(
    "/check-slug",
    response_model=SlugCheckResponse,
    summary="Check slug availability without creating the tenant",
)
async def check_slug(
    data: SlugCheckRequest,
    _: None = require_permission("super-admin:tenants:read"),
) -> SlugCheckResponse:
    if not is_valid_tenant_slug(data.slug):
        return SlugCheckResponse(
            slug=data.slug,
            available=False,
            valid_format=False,
            reason="Doit faire 2-63 caractères, minuscules + chiffres + tirets, sans tiret en début/fin",
        )

    if is_reserved_tenant_slug(data.slug):
        return SlugCheckResponse(
            slug=data.slug,
            available=False,
            valid_format=True,
            reason="Ce slug est réservé (système ou collision plateforme). Choisir un autre identifiant.",
        )

    taken = await slug_exists(data.slug)
    return SlugCheckResponse(
        slug=data.slug,
        available=not taken,
        valid_format=True,
        reason="Ce slug est déjà utilisé par un autre tenant" if taken else None,
    )
