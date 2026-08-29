"""La route qui signale qu'un eleve existe peut-etre deja.

Sortie du routeur `admin`, qui depasse largement la limite de taille du
projet. La fonctionnalite a déjà son paquet de service ; elle a maintenant
sa route, montee sous le même prefixe pour que l'URL ne bouge pas.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.schemas.duplicates import DuplicatesResponse
from app.services.duplicates.detection import find_duplicates

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/students/duplicates", response_model=DuplicatesResponse)
async def search_student_duplicates(
    last_name: str | None = Query(None, description="Nom de famille saisi"),
    first_name: str | None = Query(None, description="Prénom saisi"),
    birth_date: date | None = Query(None, description="Date de naissance, si connue"),
    enrollment_number: str | None = Query(None, description="Matricule, s'il est connu"),
    academic_year_id: int | None = Query(
        None, description="Pour signaler une inscription déjà ouverte sur cette année"
    ),
    exclude_student_id: int | None = Query(
        None, description="La fiche en cours de modification, qui ne doit pas se signaler"
    ),
    _: None = require_permission("admin:students:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> DuplicatesResponse:
    """Les fiches qui pourraient déjà être cet élève.

    Ne bloque rien et n'écrit rien : rend ce qui ressemble, et laisse la
    personne au guichet trancher. Refuser une création sur une ressemblance
    reviendrait à renvoyer un vrai nouvel élève qui porte le nom de son cousin,
    sans recours.
    """
    # La mise en forme vit dans le service, qui la possede déjà : la garder
    # ici en faisait une seconde copie, dans un routeur qui depasse deja 1300
    # lignes, pendant que celle du service n'etait appelee par personne.
    return await find_duplicates(
        db,
        last_name=last_name,
        first_name=first_name,
        birth_date=birth_date,
        enrollment_number=enrollment_number,
        academic_year_id=academic_year_id,
        exclude_student_id=exclude_student_id,
    )
