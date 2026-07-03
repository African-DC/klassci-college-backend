"""Router profil self-service — /profile/me (tout utilisateur authentifié).

Pas de `from __future__ import annotations` ici : le DELETE 204 `-> None`
casserait au chargement sous PEP 563 (cf. rule no-pep563-with-204).
"""

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.schemas.profile import MyProfileResponse, MyProfileUpdate, PhotoUrlResponse
from app.services import profile_service
from app.utils.photo_upload import save_photo_upload

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/me", response_model=MyProfileResponse)
async def get_my_profile(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> MyProfileResponse:
    """Profil de l'utilisateur connecté (nom, contact, photo, capacités self-service)."""
    return MyProfileResponse(**await profile_service.get_my_profile(db, current_user.user_id))


@router.patch("/me", response_model=MyProfileResponse)
async def update_my_profile(
    data: MyProfileUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> MyProfileResponse:
    """Met à jour les champs éditables par l'utilisateur (téléphone)."""
    return MyProfileResponse(**await profile_service.update_my_profile(db, current_user.user_id, data))


@router.post("/me/photo", response_model=PhotoUrlResponse)
async def upload_my_photo(
    file: UploadFile = File(...),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> PhotoUrlResponse:
    """L'enseignant / le personnel téléverse sa propre photo."""
    url = await save_photo_upload(file, prefix=f"u{current_user.user_id}")
    saved = await profile_service.set_my_photo(db, current_user.user_id, url)
    return PhotoUrlResponse(photo_url=saved)


@router.delete("/me/photo", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_photo(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Retire sa propre photo de profil."""
    await profile_service.set_my_photo(db, current_user.user_id, None)
