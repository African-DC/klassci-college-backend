"""Déplacer une imputation d'un frais vers un autre, sans toucher au versement.

Le manque était écrit noir sur blanc dans `lifecycle.cancel_payment` : « Une
imputation sur le mauvais frais se ré-affecte. Ni l'un ni l'autre n'existe
encore. » Faute de ce geste, la seule issue était d'annuler le versement entier
et de le ressaisir — et le 11/09/2026, sur une inscription du collège Rostan,
il a fallu envisager d'annuler 164 000 F pour déplacer 3 000 F posés sur un
article que la famille avait apporté en nature. Le journal de caisse aurait
gardé une annulation de 164 000 F pour une erreur de 3 000, et la famille
aurait reçu un reçu réimprimé racontant cette annulation.

**On déplace, on ne crée ni ne détruit.** C'est ce qui distingue ce geste de
l'annulation : le versement garde son montant, sa date, son moyen et son
caissier ; la caisse n'est pas touchée, et la clôture du jour tombe juste sans
rien savoir de cette correction. L'invariant « la somme des imputations vaut le
versement » tient donc par construction — et il est vérifié quand même, parce
que « par construction » est précisément ce qui cesse d'être vrai le jour où
l'on ajoute un chemin.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, ConflictError, NotFoundError
from app.models.fee import Payment, PaymentAllocation, PaymentStatus, cash_remaining
from app.repositories import payment_repository as repo
from app.schemas.payment import PaymentResponse
from app.services.payments import allocation_invariant
from app.services.payments._allocation import (
    _can_receive_cash,
    _pourquoi_rien_a_recevoir,
    paid_for_fees,
    recompute_fee_status,
)
from app.services.payments._correction import ensure_cashier_may_correct, motif_valide
from app.services.payments._response import payment_to_response


async def reallocate_payment(
    db: AsyncSession,
    payment_id: int,
    *,
    from_fee_id: int,
    to_fee_id: int,
    amount: Decimal,
    reason: str,
    reallocated_by: int,
    may_reallocate_any: bool,
) -> PaymentResponse:
    """Déplace `amount` de l'imputation sur `from_fee_id` vers `to_fee_id`.

    **Versement encaissé uniquement.** Un versement en attente se corrige en
    l'annulant et le ressaisissant — rien n'a bougé, et l'annulation est faite
    pour ce cas-là. Un versement annulé ne pose plus d'argent : il n'y a rien à
    déplacer. Ce geste-ci n'existe que pour le seul cas où annuler ferait
    disparaître un billet qui est dans le tiroir.

    **Même dossier.** Le frais d'arrivée appartient à l'inscription du
    versement. Déplacer de l'argent vers le dossier d'une autre famille n'est
    pas une correction d'imputation, c'est un transfert — et il se verrait
    nulle part.

    `may_reallocate_any` est sans valeur par défaut, comme son jumeau sur
    l'annulation : c'est un garde de sécurité, et un défaut permissif le
    désactiverait en silence chez le premier appelant qui l'oublierait.
    """
    motif = motif_valide(reason)

    if amount <= Decimal("0"):
        raise BusinessValidationError("Le montant à déplacer doit être supérieur à zéro.")
    if from_fee_id == to_fee_id:
        raise BusinessValidationError(
            "Le frais de départ et le frais d'arrivée sont le même : il n'y a rien à déplacer."
        )

    async with db.begin_nested():
        payment = await _load_for_reallocation(db, payment_id)

        if payment.status != PaymentStatus.COMPLETED.value:
            raise ConflictError(
                "Seul un versement encaissé se réimpute. Un versement en attente ou "
                "annulé se corrige en l'annulant puis en le ressaisissant."
            )

        if not may_reallocate_any:
            await ensure_cashier_may_correct(db, payment, reallocated_by, geste="réimputé")

        depart = _allocation_sur(payment, from_fee_id)
        if depart is None:
            raise ConflictError(
                f"Ce versement n'a rien imputé sur le frais #{from_fee_id} : "
                "il n'y a pas d'imputation à déplacer."
            )
        if amount > depart.amount:
            raise BusinessValidationError(
                f"Ce versement n'a imputé que {depart.amount} XOF sur ce frais, "
                f"or vous en déplacez {amount} XOF. On ne déplace pas plus qu'il n'y a."
            )

        frais_depart = await repo.get_enrollment_fee_for_update(db, from_fee_id)
        frais_arrivee = await repo.get_enrollment_fee_for_update(db, to_fee_id)
        if frais_depart is None or frais_arrivee is None:
            raise NotFoundError(
                "EnrollmentFee", to_fee_id if frais_arrivee is None else from_fee_id
            )

        # Un frais d'une autre inscription et un frais inexistant reçoivent
        # sciemment la même phrase, comme dans `_check_directed_allocations` :
        # répondre « introuvable » d'un côté et « pas à vous » de l'autre
        # apprendrait quels identifiants existent ailleurs, sur un objet qui
        # porte de l'argent.
        if frais_arrivee.enrollment_id != frais_depart.enrollment_id:
            raise ConflictError(
                f"Le frais #{to_fee_id} n'appartient pas à cette inscription : "
                "aucune imputation ne peut y être déplacée."
            )

        verses = await paid_for_fees(db, [frais_depart, frais_arrivee])
        deja_sur_arrivee = verses.get(frais_arrivee.id, Decimal("0"))
        if not _can_receive_cash(frais_arrivee, deja_sur_arrivee):
            raise ConflictError(_pourquoi_rien_a_recevoir(to_fee_id, frais_arrivee))

        reste = cash_remaining(frais_arrivee.status, frais_arrivee.amount, deja_sur_arrivee)
        if amount > reste:
            raise BusinessValidationError(
                f"Le frais #{to_fee_id} ne peut recevoir que {reste} XOF, or vous lui en "
                f"déplacez {amount} XOF. On n'impute jamais plus que le reste dû."
            )

        avant = _photo_des_imputations(payment)

        depart.amount -= amount
        if depart.amount <= Decimal("0"):
            # Une ligne à zéro n'est pas une trace, c'est un parasite : le point
            # par catégorie ne lit que cette table, et y afficherait un frais
            # servi de zéro franc. Ce qui a eu lieu vit dans le journal d'audit.
            await db.delete(depart)

        arrivee = _allocation_sur(payment, to_fee_id)
        if arrivee is None:
            # Jamais deux lignes pour le même frais sur le même versement :
            # `uq_payment_allocation` le refuse en base depuis la migration 0079,
            # et `inspecter` le nomme comme un défaut à lui seul.
            await repo.create_allocation(
                db, payment_id=payment.id, enrollment_fee_id=to_fee_id, amount=amount
            )
        else:
            arrivee.amount += amount
        await db.flush()

        touches = [frais_depart, frais_arrivee]
        verses = await paid_for_fees(db, touches)
        for frais in touches:
            recompute_fee_status(frais, verses.get(frais.id, Decimal("0")))
        await db.flush()

        apres = await _photo_apres(db, payment.id)
        # Le filet, sur ce qui vient d'être écrit : un déplacement ne peut pas
        # rompre l'invariant, et c'est exactement le genre de certitude qui
        # cesse d'être vraie sans qu'on s'en aperçoive.
        allocation_invariant.verifier(payment.amount, apres)

        await audit_log(
            db,
            entity_type="payment",
            action=AuditAction.UPDATE,
            user_id=reallocated_by,
            entity_id=payment.id,
            old_values={"allocations": avant},
            new_values={
                "action": "reallocation",
                "from_enrollment_fee_id": from_fee_id,
                "to_enrollment_fee_id": to_fee_id,
                "amount": str(amount),
                "reason": motif,
                "allocations": [
                    {"enrollment_fee_id": frais, "amount": str(part)} for frais, part in apres
                ],
            },
        )

    await db.commit()

    refreshed = await repo.get_payment_with_allocations(db, payment_id)
    if refreshed is None:
        raise NotFoundError("Payment", payment_id)
    return payment_to_response(refreshed)


async def _load_for_reallocation(db: AsyncSession, payment_id: int) -> Payment:
    """Verrouille le versement et ses imputations le temps du déplacement."""
    stmt = (
        select(Payment)
        .where(Payment.id == payment_id)
        .options(selectinload(Payment.allocations))
        .with_for_update(of=Payment)
    )
    payment = (await db.execute(stmt)).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Payment", payment_id)
    return payment


def _allocation_sur(payment: Payment, fee_id: int) -> PaymentAllocation | None:
    """L'imputation de ce versement sur ce frais, s'il y en a une.

    Il ne peut y en avoir qu'une : la contrainte unique le garantit. Chercher
    en mémoire plutôt qu'en base évite un aller-retour, la relation étant déjà
    chargée par le verrou.
    """
    for allocation in payment.allocations:
        if allocation.enrollment_fee_id == fee_id:
            return allocation
    return None


def _photo_des_imputations(payment: Payment) -> list[dict[str, str | int]]:
    """La ventilation avant le déplacement, pour le journal d'audit."""
    return [
        {"enrollment_fee_id": a.enrollment_fee_id, "amount": str(a.amount)}
        for a in payment.allocations
    ]


async def _photo_apres(db: AsyncSession, payment_id: int) -> list[tuple[int, Decimal]]:
    """La ventilation telle qu'elle est en base après écriture.

    Relue plutôt que déduite : c'est la seule façon que le contrôle de
    l'invariant porte sur ce qui a été écrit, et non sur ce qu'on croit avoir
    écrit. La suppression d'une ligne à zéro, notamment, ne se voit pas sur la
    collection en mémoire tant que la session n'a pas expiré la relation.
    """
    lignes = (
        await db.execute(
            select(PaymentAllocation.enrollment_fee_id, PaymentAllocation.amount).where(
                PaymentAllocation.payment_id == payment_id
            )
        )
    ).all()
    return [(int(fee_id), Decimal(str(montant))) for fee_id, montant in lignes]
