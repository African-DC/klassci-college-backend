"""Router inscriptions — CRUD /enrollments + documents.

Les endpoints paiements `/enrollments/{id}/payments` sont dans
`enrollment_payments.py` (séparation par sous-domaine, anti-god-code).

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
)
from app.schemas.admin import ArchiveRequest
from app.schemas.enrollment import (
    BulkValidateRequest,
    BulkValidateResponse,
    EnrollmentCreate,
    EnrollmentListResponse,
    EnrollmentResponse,
    EnrollmentUpdate,
    EnrollmentWithStudentCreate,
    FeeVariantResponse,
    InKindDepositResponse,
    InKindRosterResponse,
    InKindRosterRowResponse,
    NewStudentSuggestionResponse,
    ReEnrollmentCreate,
    SubscribeOptionRequest,
)
from app.services import (
    archive_service,
    enrollment_fees,
    enrollment_history,
    enrollment_service,
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

    Le motif de dérogation voyage en paramètre de requête, comme chez le jumeau
    `document_release_service` : le corps des trois créations est partagé avec
    la promotion de masse, et un champ de plus y serait un champ que personne
    n'y remplit jamais.
    """

    async def _resolve(
        override_reason: str | None = Query(
            None,
            description=(
                "Motif de dérogation. Requis pour inscrire malgré une dette "
                "d'un exercice précédent."
            ),
            max_length=500,
        ),
        may_read_amounts: bool = has_permission("payments:read"),
        may_read_status: bool = has_permission("payments:status:read"),
        may_override: bool = has_permission("enrollments:arrears:override"),
    ) -> ArrearsClearance:
        return ArrearsClearance(
            view=FinanceView.of(
                may_read_payments=may_read_amounts, may_read_status=may_read_status
            ),
            may_override=may_override,
            override_reason=override_reason,
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
        db, data, created_by=current_user.user_id, arrears=arrears
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
        db, data, created_by=current_user.user_id, arrears=arrears
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
        db, data, created_by=current_user.user_id, arrears=arrears
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
    """
    suggested, reason = await enrollment_history.suggest_new_student(
        db, student_id, academic_year_id
    )
    return NewStudentSuggestionResponse(suggested=suggested, reason=reason)


@router.get(
    "/in-kind-roster",
    response_model=InKindRosterResponse,
    summary="La classe entiere, pour la saisie en lot du profil et des depots",
)
async def in_kind_roster(
    class_id: int = Query(..., description="Classe sur laquelle l'educateur travaille"),
    academic_year_id: int = Query(..., description="Annee de la classe"),
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> InKindRosterResponse:
    """Ce qu'il reste a renseigner sur chaque eleve d'une classe.

    Une classe a la fois, jamais toute l'ecole : c'est l'unite de travail de
    l'educateur, sa liste a la main. En un appel, parce que soixante-dix-huit
    fiches ouvertes une par une, c'est un travail qui ne se termine pas.

    Chaque ligne porte le profil tel qu'il est, `null` compris, et seulement
    les articles que cette inscription-la peut recevoir. Une case affichee sur
    un frais que l'eleve ne doit pas serait une invitation a se tromper.
    """
    lignes = await enrollment_fees.in_kind_roster(
        db, class_id=class_id, academic_year_id=academic_year_id
    )
    return InKindRosterResponse(
        items=[InKindRosterRowResponse.model_validate(ligne) for ligne in lignes]
    )


@router.get("/fee-variants", response_model=list[FeeVariantResponse])
async def get_applicable_fee_variants(
    class_id: int = Query(..., description="ID de la classe pour la resolution des frais"),
    academic_year_id: int | None = Query(
        None,
        description=(
            "AY pour le matching des frais. Si omis, l'AY courante est utilisée. "
            "Class étant universel (refactor #97), l'AY n'est plus inférée depuis la classe."
        ),
    ),
    assignment_status: str | None = Query(
        None,
        description="Statut d'affectation de l'inscription, pour resoudre les tarifs qui en dependent.",
    ),
    is_new_student: bool | None = Query(
        None,
        description=(
            "Profil de l'inscription. Omis, l'apercu ne montre que les tarifs "
            "sans profil, comme une inscription non tranchee."
        ),
    ),
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[FeeVariantResponse]:
    """Retourne les fee variants applicables pour une classe donnee.

    Les deux dimensions sont passees au service, et c'est le point de cet
    endpoint : sans elles il resout les tarifs comme une inscription dont on
    ne sait rien, donc en ecartant tout tarif porteur d'une portee ou d'un
    profil. Le guichet lisait alors une facture ou la chemise cartonnee
    n'apparaissait jamais, alors que l'inscription creee juste apres la
    portait. L'apercu et la generation reelle doivent annoncer la meme chose.
    """
    return await enrollment_fees.get_applicable_fee_variants(
        db,
        class_id,
        academic_year_id,
        assignment_status=assignment_status,
        is_new_student=is_new_student,
    )


@router.get("/{enrollment_id}", response_model=EnrollmentResponse)
async def get_enrollment(
    enrollment_id: int,
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Retourne une inscription par ID."""
    return await enrollment_service.get_enrollment(db, enrollment_id)


@router.patch(
    "/{enrollment_id}/fees/{fee_id}/in-kind-deposit",
    response_model=InKindDepositResponse,
)
async def mark_in_kind_deposit(
    enrollment_id: int,
    fee_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> InKindDepositResponse:
    """Dépôt tardif : pending sans versement → déposé. Sinon 409."""
    async with db.begin_nested():
        fee = await enrollment_fees.mark_in_kind_deposit(
            db,
            enrollment_id=enrollment_id,
            fee_id=fee_id,
            deposited_by=current_user.user_id,
        )
    await db.commit()
    return InKindDepositResponse(
        id=fee.id,
        status=fee.status,
        deposited_at=fee.deposited_at,
        deposited_by_user_id=fee.deposited_by_user_id,
    )


@router.delete(
    "/{enrollment_id}/fees/{fee_id}/in-kind-deposit",
    response_model=InKindDepositResponse,
    summary="Annuler un depot en nature pose par erreur",
)
async def cancel_in_kind_deposit(
    enrollment_id: int,
    fee_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> InKindDepositResponse:
    """La ligne redevient due. 409 si elle n'etait pas deposee.

    Marquer un article depose retire la ligne du du, et l'application n'offrait
    aucun retour : un depot pose par erreur a deja du etre corrige a la main
    dans la base. Avec une saisie en lot, ou l'educateur coche quarante cases
    d'affilee, ce manque n'etait plus tenable.

    Rend le meme corps que la pose : l'ecran lit un seul contrat, quel que
    soit le sens du geste.
    """
    async with db.begin_nested():
        fee = await enrollment_fees.cancel_in_kind_deposit(
            db,
            enrollment_id=enrollment_id,
            fee_id=fee_id,
            cancelled_by=current_user.user_id,
        )
    await db.commit()
    return InKindDepositResponse(
        id=fee.id,
        status=fee.status,
        deposited_at=fee.deposited_at,
        deposited_by_user_id=fee.deposited_by_user_id,
    )


@router.patch("/{enrollment_id}", response_model=EnrollmentResponse)
async def update_enrollment(
    enrollment_id: int,
    data: EnrollmentUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Met à jour le statut ou les notes d'une inscription (patch partiel)."""
    return await enrollment_service.update_enrollment(
        db, enrollment_id, data, updated_by=current_user.user_id
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
    return await enrollment_service.validate_enrollment(
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
    resultat = await enrollment_service.validate_enrollments_in_bulk(
        db, payload.enrollment_ids, validated_by=current_user.user_id
    )
    return BulkValidateResponse(**resultat)


# ---------------------------------------------------------------------------
# Optional fee subscriptions
# ---------------------------------------------------------------------------


@router.post(
    "/{enrollment_id}/options",
    status_code=status.HTTP_201_CREATED,
)
async def subscribe_option(
    enrollment_id: int,
    data: SubscribeOptionRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Souscrit un élève à une option de frais facultatif."""
    async with db.begin_nested():
        result = await enrollment_service.subscribe_optional_fee(
            db,
            enrollment_id=enrollment_id,
            optional_fee_option_id=data.optional_fee_option_id,
            created_by=current_user.user_id,
        )
    await db.commit()
    return result


@router.delete(
    "/{enrollment_id}/options/{option_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unsubscribe_option(
    enrollment_id: int,
    option_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Désinscrit un élève d'une option de frais facultatif."""
    async with db.begin_nested():
        await enrollment_service.unsubscribe_optional_fee(
            db,
            enrollment_id=enrollment_id,
            option_id=option_id,
            deleted_by=current_user.user_id,
        )
    await db.commit()
