"""Router paiements — CRUD /payments + bordereau journalier."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_read import audit_read
from app.core.dependencies import (
    TokenData,
    get_current_user,
    get_tenant_db,
    has_permission,
    require_permission,
)
from app.core.payment_methods import method_label
from app.repositories.payment_filters import PaymentFilters
from app.routers._pdf_helpers import binary_response, pdf_response
from app.schemas.payment import (
    CashierOption,
    CategoryLedgerResponse,
    PaymentCancel,
    PaymentCreate,
    PaymentListResponse,
    PaymentMethodListResponse,
    PaymentMethodOption,
    PaymentResponse,
    PaymentSummaryResponse,
)
from app.services import (
    daily_cash_book_service,
    fee_category_ledger,
    payment_service,
    payments_journal_service,
)
from app.services.payments import methods as payment_methods
from app.services.payments.scope import cashier_scope

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", response_model=PaymentListResponse)
async def list_payments(
    status_filter: str | None = Query(None, alias="status"),
    method: str | None = Query(None),
    enrollment_fee_id: int | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    received_by: int | None = Query(
        None, description="N'afficher que la caisse de cet encaisseur."
    ),
    search: str | None = Query(
        None, description="Nom ou matricule de l'eleve, ou reference du versement."
    ),
    fee_category_id: int | None = Query(
        None, description="Ne garder que les versements imputes sur cette categorie."
    ),
    academic_year_id: int | None = Query(
        None,
        description="Ne garder que les versements d'inscriptions de cette annee scolaire.",
    ),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: TokenData = Depends(get_current_user),
    can_read_all: bool = has_permission("payments:read:all"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentListResponse:
    """Liste paginée des paiements avec filtres optionnels.

    Un caissier n'a pas `payments:read:all` : il ne lit que les versements
    qu'il a lui-même encaissés, et le paramètre `received_by` ne lui sert pas
    de passe-droit vers la caisse d'un collègue.
    """
    return await payment_service.list_payments(
        db,
        filters=PaymentFilters(
            status=status_filter,
            method=method,
            enrollment_fee_id=enrollment_fee_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
            fee_category_id=fee_category_id,
            academic_year_id=academic_year_id,
            received_by=cashier_scope(
                requested_received_by=received_by,
                can_read_all=can_read_all,
                current_user_id=current_user.user_id,
            ),
        ),
        page=page,
        size=size,
    )


@router.post("", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    data: PaymentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("payments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentResponse:
    """Enregistre un nouveau paiement."""
    return await payment_service.create_payment(db, data, actor=current_user)


# NOTE: /methods and /summary MUST be defined BEFORE /{payment_id}
# to avoid FastAPI matching "methods" / "summary" as a payment_id path param.
@router.get(
    "/methods",
    response_model=PaymentMethodListResponse,
    summary="Moyens de paiement que l'utilisateur courant peut saisir",
)
async def list_my_payment_methods(
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("payments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentMethodListResponse:
    """Ce que le formulaire d'encaissement doit proposer, et rien de plus.

    Croise ce que l'établissement accepte et ce que le profil autorise. Le
    sélecteur se remplit d'ici plutôt que d'une liste figée côté écran :
    proposer un moyen pour le refuser à l'enregistrement ferait recommencer la
    saisie devant la famille.
    """
    keys = await payment_methods.allowed_methods_for(db, current_user)
    return PaymentMethodListResponse(
        items=[PaymentMethodOption(key=key, label=method_label(key)) for key in keys]
    )


@router.get("/summary", response_model=PaymentSummaryResponse)
async def get_payments_summary(
    academic_year_id: int | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    method: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    search: str | None = Query(None),
    fee_category_id: int | None = Query(None),
    received_by: int | None = Query(
        None,
        description=(
            "Restreint a une caisse. Accepte ici parce que l'ecran l'envoie : "
            "sans lui, filtrer « Encaisse par » donnait un tableau de douze "
            "lignes sous un bandeau qui en comptait cent vingt-huit."
        ),
    ),
    current_user: TokenData = Depends(get_current_user),
    can_read_all: bool = has_permission("payments:read:all"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentSummaryResponse:
    """Les chiffres du bandeau, sur le meme perimetre que le tableau dessous.

    Les filtres de l'ecran s'appliquent a la moitie caisse : nombre de
    versements, en attente, annules. Filtrer sur « Annule » et lire malgre
    tout le total de l'annee ferait dire au bandeau autre chose que la liste.

    Le recouvrement, lui, ne les suit pas, et c'est voulu : il parle de la
    dette de l'ecole, pas des lignes affichees. Filtrer une dette sur un
    moyen de paiement ne veut rien dire. L'ecran doit le signaler plutot que
    de laisser croire que les deux chiffres repondent a la meme question.

    Sans cloisonnement, une caissiere lisait « 128 versements » au-dessus d'un
    tableau qui n'en contenait que trois : le bandeau parlait de l'ecole, la
    liste de sa caisse. Les deux suivent desormais la meme regle.

    Le recouvrement de l'etablissement ne lui est pas servi pour autant. Il
    revient vide plutot qu'a zero : un zero se lirait « rien n'est du », ce
    qui serait faux.
    """
    return await payment_service.get_payments_summary(
        db,
        academic_year_id=academic_year_id,
        filters=PaymentFilters(
            status=status_filter,
            method=method,
            date_from=date_from,
            date_to=date_to,
            search=search,
            fee_category_id=fee_category_id,
            academic_year_id=academic_year_id,
        ),
        received_by=cashier_scope(
            requested_received_by=received_by,
            can_read_all=can_read_all,
            current_user_id=current_user.user_id,
        ),
    )


# NOTE: /cashiers MUST be defined BEFORE /{payment_id}
@router.get("/cashiers", response_model=list[CashierOption])
async def list_cashiers(
    current_user: TokenData = Depends(get_current_user),
    can_read_all: bool = has_permission("payments:read:all"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[CashierOption]:
    """Les encaisseurs proposables dans le filtre « Encaissé par ».

    Un caissier cloisonne sa vue sur lui-même : lui servir la liste de ses
    collègues lui apprendrait qui tient les autres guichets, alors que le
    filtre ne pourrait de toute façon rien lui montrer d'eux.
    """
    if not can_read_all:
        return await payments_journal_service.own_cashier_option(db, current_user.user_id)
    return await payments_journal_service.list_cashier_options(db)


# NOTE: /export MUST be defined BEFORE /{payment_id}
@router.get(
    "/export",
    summary="Journal des versements (PDF ou Excel) — mêmes filtres que la liste",
)
async def export_payments(
    status_filter: str | None = Query(None, alias="status"),
    method: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    received_by: int | None = Query(None),
    academic_year_id: int | None = Query(None),
    export_format: str = Query("pdf", alias="format", pattern="^(pdf|xlsx)$"),
    current_user: TokenData = Depends(get_current_user),
    can_read_all: bool = has_permission("payments:read:all"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Exporte le journal des versements au gabarit officiel de l'établissement.

    Le cloisonnement est celui de la liste, appliqué dans la même requête : un
    export qui déverserait toutes les caisses contournerait la restriction de
    l'écran sans que personne ne le voie, puisqu'on ne relit pas un classeur
    de la même façon qu'un tableau.
    """
    filters = PaymentFilters(
        status=status_filter,
        method=method,
        date_from=date_from,
        date_to=date_to,
        academic_year_id=academic_year_id,
        received_by=cashier_scope(
            requested_received_by=received_by,
            can_read_all=can_read_all,
            current_user_id=current_user.user_id,
        ),
    )
    jour = date.today().isoformat()
    if export_format == "xlsx":
        return await binary_response(
            lambda: payments_journal_service.get_journal_xlsx(
                db, filters=filters, restricted=not can_read_all
            ),
            filename=f"journal-versements-{jour}.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            error_context="journal des versements (Excel)",
            disposition="attachment",
        )
    return await pdf_response(
        lambda: payments_journal_service.get_journal_pdf(
            db, filters=filters, restricted=not can_read_all
        ),
        filename=f"journal-versements-{jour}.pdf",
        error_context="journal des versements",
    )


# NOTE: /settlement/category/export MUST be defined BEFORE /{payment_id}
@router.get(
    "/settlement/category/export",
    summary="Le point d'une categorie au format classeur",
)
async def export_fee_category_point(
    category_id: int = Query(...),
    academic_year_id: int = Query(...),
    class_id: int | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    received_by: int | None = Query(None),
    export_format: str = Query("pdf", alias="format", pattern="^(pdf|xlsx)$"),
    inline: bool = Query(False, description="Afficher au lieu de telecharger."),
    current_user: TokenData = Depends(get_current_user),
    can_read_all: bool = has_permission("payments:read:all"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Le document que le comptable tire, ou la caissiere pour sa seule caisse.

    Meme cloisonnement que l'ecran, et pour la meme raison : un export garde
    moins fermement que la vue qu'il reproduit est une porte derobee, et c'est
    le genre de fuite qu'on ne voit jamais en regardant l'interface.

    Le classeur porte en en-tete, en toutes lettres, le fait qu'il ne couvre
    qu'une caisse quand c'est le cas. Sans cette ligne, un document de guichet
    se lirait comme le compte de l'ecole entiere.
    """
    criteres = {
        "category_id": category_id,
        "academic_year_id": academic_year_id,
        "class_id": class_id,
        "date_from": date_from,
        "date_to": date_to,
        "received_by": cashier_scope(
            requested_received_by=received_by,
            can_read_all=can_read_all,
            current_user_id=current_user.user_id,
        ),
        "consolide": can_read_all,
    }
    jour = date.today().isoformat()

    if export_format == "xlsx":
        return await binary_response(
            lambda: fee_category_ledger.get_category_ledger_xlsx(db, **criteres),
            filename=f"point-categorie-{jour}.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            error_context="point sur une categorie de frais (classeur)",
            disposition="attachment",
        )

    # `inline` sert l'apercu : le meme document, affiche au lieu d'etre
    # telecharge. Un comptable qui verifie une periode avant de l'envoyer a un
    # prestataire ne veut pas six fichiers dans son dossier de telechargements.
    return await pdf_response(
        lambda: fee_category_ledger.get_category_ledger_pdf(db, **criteres),
        filename=f"point-categorie-{jour}.pdf",
        error_context="point sur une categorie de frais",
        disposition="inline" if inline else "attachment",
    )


# NOTE: /settlement/category MUST be defined BEFORE /{payment_id}
@router.get(
    "/settlement/category",
    response_model=CategoryLedgerResponse,
    summary="Le point sur une categorie de frais : entre en argent, en nature, et du",
)
async def fee_category_point(
    category_id: int = Query(..., description="La categorie de frais regardee."),
    academic_year_id: int = Query(..., description="Annee lue."),
    class_id: int | None = Query(None, description="Reduire a une classe."),
    date_from: datetime | None = Query(None, description="Debut de periode, inclus."),
    date_to: datetime | None = Query(None, description="Fin de periode, exclue."),
    received_by: int | None = Query(None, description="Restreindre a une caisse."),
    current_user: TokenData = Depends(get_current_user),
    can_read_all: bool = has_permission("payments:read:all"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> CategoryLedgerResponse:
    """Une vue detaillee sur un frais : qui a paye, qui a depose, qui doit encore.

    **Ce qui est entre se cloisonne ; ce qui reste du ne se cloisonne pas.**

    Une caissiere lit ce qu'elle a encaisse sur cette categorie : c'est un fait
    sur sa caisse, et le lui refuser l'empecherait de faire son point. Le
    filtre de caisse est celui de la liste et des exports, decide par
    `cashier_scope` — un filtre demande n'a jamais servi de passe-droit.

    Ce qu'une famille doit encore, en revanche, se calcule sur tout l'argent
    recu : filtre sur un guichet, il annoncerait une dette chez une famille qui
    a paye a cote. Sans `payments:read:all`, il n'est donc pas calcule du tout,
    et la reponse le dit par `consolide: false` plutot que de rendre un zero
    qu'on prendrait pour un solde.

    La periode borne les evenements — versements et depots. Elle ne borne pas
    le reste du, qui est un etat et vaut a l'instant ou on le lit.
    """
    ledger = await fee_category_ledger.load_category_ledger(
        db,
        category_id=category_id,
        academic_year_id=academic_year_id,
        class_id=class_id,
        date_from=date_from,
        date_to=date_to,
        received_by=cashier_scope(
            requested_received_by=received_by,
            can_read_all=can_read_all,
            current_user_id=current_user.user_id,
        ),
        consolide=can_read_all,
    )
    return CategoryLedgerResponse.model_validate(ledger)


# NOTE: /daily-cash-book MUST be defined BEFORE /{payment_id}
@router.get(
    "/daily-cash-book",
    summary="Bordereau journalier (PDF) — récap des versements d'une date",
)
async def get_daily_cash_book(
    target_date: date | None = Query(
        None,
        alias="date",
        description="Date à imprimer (YYYY-MM-DD). Par défaut : aujourd'hui.",
    ),
    current_user: TokenData = Depends(get_current_user),
    can_read_all: bool = has_permission("payments:read:all"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Génère le bordereau journalier signé pour la comptabilité.

    Groupe les paiements de la date par méthode (espèces / mobile money /
    virement / chèque), total par méthode + total général, signatures
    Caissier / Comptabilité.

    Un caissier n'obtient que SA caisse : sans ce filtre, il imprimerait les
    encaissements de toute l'école. Le comptable, lui, obtient le document
    consolidé.
    """
    target = target_date or date.today()
    return await pdf_response(
        lambda: daily_cash_book_service.get_daily_cash_book_pdf(
            db,
            target,
            cashier_user_id=current_user.user_id,
            restrict_to_cashier=not can_read_all,
        ),
        filename=f"bordereau-{target.isoformat()}.pdf",
        error_context=f"bordereau journalier {target.isoformat()}",
    )


# NOTE: /student/{enrollment_id} MUST be defined BEFORE /{payment_id}
# to avoid FastAPI matching "student" as a payment_id path param.
@router.get(
    "/student/{enrollment_id}",
    response_model=list[PaymentResponse],
)
async def get_student_payments(
    enrollment_id: int,
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[PaymentResponse]:
    """Retourne tous les paiements d'un élève via son enrollment."""
    return await payment_service.get_student_payments(db, enrollment_id)


# NOTE: /{payment_id}/receipt MUST be defined BEFORE /{payment_id}
# to avoid FastAPI matching "receipt" as part of a different route.
@router.get("/{payment_id}/receipt")
async def get_payment_receipt(
    payment_id: int,
    _read: None = audit_read("payment", param="payment_id"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Genere et retourne le recu de paiement en PDF."""
    return await pdf_response(
        lambda: payment_service.get_payment_receipt_pdf(db, payment_id),
        filename=f"recu_{payment_id}.pdf",
        error_context=f"reçu paiement {payment_id}",
    )


@router.post("/{payment_id}/validate", response_model=PaymentResponse)
async def validate_payment(
    payment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("payments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentResponse:
    """Valide un paiement (pending → completed)."""
    return await payment_service.validate_payment(db, payment_id, validated_by=current_user.user_id)


@router.post("/{payment_id}/cancel", response_model=PaymentResponse)
async def cancel_payment(
    payment_id: int,
    data: PaymentCancel,
    current_user: TokenData = Depends(get_current_user),
    may_cancel_any: bool = has_permission("payments:cancel:any"),
    _: None = require_permission("payments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentResponse:
    """Annule un versement, motif obligatoire.

    Le comptable corrige n'importe quel versement. Le caissier ne corrige que
    sa propre saisie, et seulement tant que sa journée n'est pas clôturée.
    """
    return await payment_service.cancel_payment(
        db,
        payment_id,
        reason=data.reason,
        cancelled_by=current_user.user_id,
        may_cancel_any=may_cancel_any,
    )


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: int,
    _read: None = audit_read("payment", param="payment_id"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentResponse:
    """Retourne un paiement par ID."""
    return await payment_service.get_payment(db, payment_id)
