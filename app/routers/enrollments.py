"""Router inscriptions — CRUD /enrollments + documents.

Les endpoints paiements `/enrollments/{id}/payments` sont dans
`enrollment_payments.py`, les dépôts en nature et l'aperçu des tarifs dans
`enrollment_in_kind.py`, les options facultatives dans
`enrollment_options.py` (séparation par sous-domaine, anti-god-code).

Les trois créations d'inscription résolvent ici, et ici seulement, ce que
l'appelant a le droit de faire face à une ardoise d'un exercice révolu :
trois permissions lues dans la matrice, jamais un rôle. Le service reçoit le
résultat et n'a rien à demander à personne.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    TokenData,
    get_current_user,
    get_tenant_db,
    has_permission,
    require_permission,
    resolve_permission,
)
from app.models.enrollment import EnrollmentStatus
from app.schemas.admin import ArchiveRequest
from app.schemas.enrollment import (
    BulkValidateRequest,
    BulkValidateResponse,
    EnrollmentCreate,
    EnrollmentListResponse,
    EnrollmentResponse,
    EnrollmentUpdate,
    EnrollmentWithStudentCreate,
    NewStudentSuggestionResponse,
    ReEnrollmentCreate,
)
from app.services import (
    archive_service,
    enrollment_history,
    enrollment_service,
    enrollment_validation,
    fees_paid,
)
from app.services.enrollment_archive import ENROLLMENT_KIND
from app.services.enrollment_arrears import ArrearsClearance
from app.services.finance_visibility import FinanceView

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


def arrears_clearance() -> Any:
    """Ce que l'appelant peut faire, et voir, d'une ardoise d'un exercice révolu.

    Trois droits, tous lus dans la matrice :

    - `payments:read` — le montant apparaît dans le refus.
    - `payments:status:read` — un booléen, et rien de plus : on valide un
      dossier sans apprendre la situation économique du foyer.
    - `enrollments:arrears:override` — le droit de passer outre, semé par la
      migration `0080` et porté par la direction seule tant qu'une école n'en
      décide pas autrement.

    `has_permission` et non `require_permission` : ces droits ne décident pas
    de l'accès à la route — la secrétaire inscrit sans lire les paiements — ils
    en décident l'ÉTENDUE. C'est exactement le cas que cette dépendance sert
    déjà pour le journal des versements.

    **Le motif ne passe pas par ici** : il vient du corps de la requête, et
    chaque route le greffe par `clearance.avec_motif(data.override_reason)`.
    Une dépendance est résolue avant que le corps ne soit lu, donc le motif
    n'aurait pu venir que de l'adresse — or il nomme une famille, et une URL
    finit dans les journaux d'accès du serveur et chez tous les
    intermédiaires. Le dépôt porte déjà cette règle, écrite dans
    `tests/test_enrollment_purge.py`.
    """

    async def _resolve(
        may_read_amounts: bool = has_permission("payments:read"),
        may_read_status: bool = has_permission("payments:status:read"),
        may_override: bool = has_permission("enrollments:arrears:override"),
    ) -> ArrearsClearance:
        return ArrearsClearance(
            view=FinanceView.of(
                may_read_payments=may_read_amounts, may_read_status=may_read_status
            ),
            may_override=may_override,
        )

    return Depends(_resolve)


@router.get("", response_model=EnrollmentListResponse)
async def list_enrollments(
    class_id: int | None = Query(None),
    student_id: int | None = Query(None),
    status: str | None = Query(None),
    academic_year_id: int | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentListResponse:
    """Liste paginée des inscriptions avec filtres optionnels."""
    return await enrollment_service.list_enrollments(
        db,
        class_id=class_id,
        student_id=student_id,
        status=status,
        academic_year_id=academic_year_id,
        search=search,
        page=page,
        size=size,
    )


@router.post("", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
async def create_enrollment(
    data: EnrollmentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:create"),
    arrears: ArrearsClearance = arrears_clearance(),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Crée une nouvelle inscription.

    Répond 402 quand l'établissement bloque au-delà d'un seuil et que l'élève
    traîne une dette d'un exercice révolu. 402 et non 403 : « il faut payer »
    n'est pas « vous n'avez pas le droit ».
    """
    return await enrollment_service.create_enrollment(
        db,
        data,
        created_by=current_user.user_id,
        arrears=arrears.avec_motif(data.override_reason),
    )


@router.post(
    "/with-student",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_enrollment_with_student(
    data: EnrollmentWithStudentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:create"),
    arrears: ArrearsClearance = arrears_clearance(),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Cree un eleve + parent optionnel + inscription en une seule operation.

    Gardee par la meme porte que `POST /enrollments`, et pas par habitude : un
    controle sur une seule des deux ne servirait a rien, c'est ici qu'une
    reinscription saisie comme un nouvel eleve passerait.
    """
    return await enrollment_service.create_enrollment_with_student(
        db,
        data,
        created_by=current_user.user_id,
        arrears=arrears.avec_motif(data.override_reason),
    )


@router.post(
    "/re-enroll",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def re_enroll_student(
    data: ReEnrollmentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:create"),
    arrears: ArrearsClearance = arrears_clearance(),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Re-inscrit un eleve existant dans une nouvelle classe/annee.

    Le chemin le plus exposé du lot : c'est la réinscription qui fait sortir
    une ardoise de l'exercice précédent des deux portails, puisque tous deux
    lisent la dernière inscription de l'élève.
    """
    return await enrollment_service.re_enroll_student(
        db,
        data,
        created_by=current_user.user_id,
        arrears=arrears.avec_motif(data.override_reason),
    )


@router.get(
    "/new-student-suggestion",
    response_model=NewStudentSuggestionResponse,
    summary="Suggest whether a student is new for a given academic year",
)
async def suggest_new_student(
    student_id: int = Query(..., description="Eleve qu'on s'apprete a inscrire"),
    academic_year_id: int = Query(
        ...,
        description="Année pour laquelle on inscrit : l'antériorité se juge par rapport à elle.",
    ),
    _: None = require_permission("enrollments:create"),
    may_read_amounts: bool = has_permission("payments:read"),
    may_read_status: bool = has_permission("payments:status:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> NewStudentSuggestionResponse:
    """Ce que la case « nouvel élève » doit afficher avant que la secrétaire ne tranche.

    Trois réponses possibles, et `null` en est une : tant que l'établissement
    n'a pas déclaré ses années passées exploitables dans ses réglages, rien ne
    permet de dire qui est nouveau. La phrase le lui explique, et elle coche
    elle-même.

    Même droit que la création d'une inscription : cette suggestion ne se lit
    que pour remplir ce formulaire-là. Elle vit avec les inscriptions et non
    dans le routeur d'administration : son sujet est l'inscription, et c'est
    la seule raison qui doit décider où vit un endpoint.

    Le chemin la place AVANT `/{enrollment_id}` : sans cela, FastAPI ferait
    correspondre `new-student-suggestion` au paramètre d'identifiant et
    rendrait une erreur de validation.

    Elle rend aussi ce que l'élève doit encore sur les AUTRES exercices. C'est
    le dernier écran où quelqu'un regarde le dossier avant que la
    réinscription ne fasse basculer les portails et la fiche élève sur la
    nouvelle année : une dette qu'on ne voit pas ici ne se reverra plus.

    Le droit de la lire ne se déduit pas de celui d'inscrire : le secrétariat
    porte `payments:read`, l'éducateur `payments:status:read`, et les deux
    montent des inscriptions. Les deux booléens se résolvent donc ici et se
    passent au service, qui ne connaît ni rôle ni permission.
    """
    suggested, reason = await enrollment_history.suggest_new_student(
        db, student_id, academic_year_id
    )
    arrears = await fees_paid.arrears_outside_year(
        db,
        student_id=student_id,
        academic_year_id=academic_year_id,
        finance=FinanceView.of(may_read_payments=may_read_amounts, may_read_status=may_read_status),
    )
    return NewStudentSuggestionResponse(suggested=suggested, reason=reason, **arrears)


@router.get("/{enrollment_id}", response_model=EnrollmentResponse)
async def get_enrollment(
    enrollment_id: int,
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Retourne une inscription par ID."""
    return await enrollment_service.get_enrollment(db, enrollment_id)


@router.patch("/{enrollment_id}", response_model=EnrollmentResponse)
async def update_enrollment(
    enrollment_id: int,
    data: EnrollmentUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Met à jour le statut ou les notes d'une inscription (patch partiel).

    Passer le statut à « valide » par ici est une validation : elle exige le
    même droit que `POST /{id}/validate`, faute de quoi le droit de modifier
    un dossier suffisait à le valider. Le droit n'est lu que si le statut
    demandé est « valide » ; le service décide s'il s'agit d'une transition.
    """
    peut_valider = data.status == EnrollmentStatus.VALIDE.value and await resolve_permission(
        current_user, db, "enrollments:validate"
    )
    return await enrollment_service.update_enrollment(
        db, enrollment_id, data, updated_by=current_user.user_id, peut_valider=peut_valider
    )


# Les trois gestes de corbeille passent par `archive_service`, comme ceux de
# l'élève, du parent, de l'enseignant et du personnel : motif obligatoire,
# passage par la corbeille avant toute destruction, journal et courriel. Seule
# l'adresse reste propre à l'inscription, le front l'appelle ici.
@router.post("/{enrollment_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_enrollment(
    enrollment_id: int,
    data: ArchiveRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Place une inscription dans la corbeille. Réversible."""
    await archive_service.archive_record(
        db, ENROLLMENT_KIND, enrollment_id, reason=data.reason, actor_id=current_user.user_id
    )


@router.post("/{enrollment_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_enrollment(
    enrollment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Sort une inscription de la corbeille."""
    await archive_service.restore_record(
        db, ENROLLMENT_KIND, enrollment_id, actor_id=current_user.user_id
    )


@router.delete(
    "/{enrollment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Réservé à la direction : c'est le seul geste du logiciel qui ne se rattrape pas. "
        "Le motif voyage dans le corps de la requête, jamais dans l'URL : une URL finit "
        "dans les journaux d'accès du serveur et chez les intermédiaires, et « exclu pour "
        "vol » n'a rien à y faire."
    ),
)
async def delete_enrollment(
    enrollment_id: int,
    data: ArchiveRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("archive:purge"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime définitivement une inscription déjà placée dans la corbeille."""
    await archive_service.purge_record(
        db, ENROLLMENT_KIND, enrollment_id, reason=data.reason, actor_id=current_user.user_id
    )


@router.post(
    "/{enrollment_id}/validate",
    response_model=EnrollmentResponse,
    summary="Valider une inscription",
    description=(
        "Transitionne une inscription `prospect` ou `en_validation` vers `valide`. "
        "Endpoint dédié pour audit log explicite et transition guard. Refuse les "
        "autres statuts avec 422."
    ),
)
async def validate_enrollment(
    enrollment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:validate"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Valide une inscription (transition prospect/en_validation → valide)."""
    return await enrollment_validation.validate_enrollment(
        db, enrollment_id, validated_by=current_user.user_id
    )


@router.post(
    "/bulk-validate",
    response_model=BulkValidateResponse,
    summary="Valider plusieurs inscriptions",
    description=(
        "Valide une liste d'inscriptions. Une inscription qui refuse la "
        "transition n'arrête pas les autres : chaque échec est rendu avec son "
        "motif, en face de son identifiant."
    ),
)
async def bulk_validate_enrollments(
    payload: BulkValidateRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:validate"),
    db: AsyncSession = Depends(get_tenant_db),
) -> BulkValidateResponse:
    """Valide une cohorte en une fois, plutôt que dossier par dossier."""
    resultat = await enrollment_validation.validate_enrollments_in_bulk(
        db, payload.enrollment_ids, validated_by=current_user.user_id
    )
    return BulkValidateResponse(**resultat)
