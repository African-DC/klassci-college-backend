"""Où va l'argent d'un versement. Fonctions pures, testables sans base.

Ce module porte les trois questions, et il est seul à les porter : quels frais
peuvent encore recevoir de l'argent, ce qui interdirait d'honorer la
répartition demandée, et comment le montant se distribue.

`resolve_allocation` est la porte d'entrée. L'aperçu et l'enregistrement
l'appellent tous les deux sur les mêmes données : l'un affiche la réponse au
caissier pendant qu'il tape, l'autre l'écrit. C'est ce qui garantit que l'écran
ne promet jamais une imputation que la caisse refusera.

Le recalcul de `fee.status` vit ici aussi, appelé par `recording.py` à la
création et par `lifecycle.py` à l'annulation comme à la validation.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    cash_remaining,
    is_in_kind,
    is_not_cash_due,
)
from app.services import fees_paid


def _cascade_by_priority(
    amount: Decimal,
    fees_with_paid: list[tuple[EnrollmentFee, Decimal]],
) -> tuple[list[tuple[EnrollmentFee, Decimal]], Decimal]:
    """Distribue `amount` aux fees par ordre fourni. Retourne (splits, surplus).

    `fees_with_paid` est attendu déjà trié par priorité ASC. Chaque entrée =
    (fee, total_paid_so_far). Cette fonction est pure : aucune I/O DB, aucune
    mutation. Testable unitaire avec des dataclasses synthétiques.
    """
    remaining = amount
    splits: list[tuple[EnrollmentFee, Decimal]] = []
    for fee, paid_so_far in fees_with_paid:
        if remaining <= 0:
            break
        fee_remaining = cash_remaining(fee.status, fee.amount, paid_so_far)
        if fee_remaining <= 0:
            continue
        allocated = min(remaining, fee_remaining)
        splits.append((fee, allocated))
        remaining -= allocated
    return splits, remaining


def _merge_directed_lines(items: Iterable[tuple[int, Decimal]]) -> dict[int, Decimal]:
    """Regroupe les lignes qui visent le même frais. Pure.

    Deux lignes sur un même frais sont une seule imputation de leur somme, et
    non deux imputations calculées chacune sur le même reste dû : c'est ainsi
    qu'on écrirait deux fois le même argent. Le regroupement précède toute
    vérification, pour que le plafond du frais soit opposé au total réel.
    """
    merged: dict[int, Decimal] = {}
    for fee_id, amount in items:
        merged[fee_id] = merged.get(fee_id, Decimal("0")) + amount
    return merged


def _can_receive_cash(fee: EnrollmentFee, paid: Decimal) -> bool:
    """Ce frais peut-il encore recevoir de l'argent ?

    Seule définition dans le code, et on la demande par `plannable_fees`. `cash_remaining` ne suffit pas : elle ignore
    le statut « soldé », et un frais payé dont les versements ne seraient pas
    encore relus paraîtrait redevable. La cascade, la répartition nommée et le
    contrôle des imputations doivent voir exactement la même liste, sinon
    l'aperçu propose un frais que l'enregistrement refuse.
    """
    encaissables = (EnrollmentFeeStatus.PENDING.value, EnrollmentFeeStatus.PARTIAL.value)
    return fee.status in encaissables and cash_remaining(fee.status, fee.amount, paid) > 0


def plannable_fees(
    fees_with_paid: list[tuple[EnrollmentFee, Decimal]],
) -> list[tuple[EnrollmentFee, Decimal]]:
    """Les frais qu'un versement peut servir, dans l'ordre reçu."""
    return [(fee, paid) for fee, paid in fees_with_paid if _can_receive_cash(fee, paid)]


@dataclass(frozen=True)
class AllocationProblem:
    """Ce qui empêche d'honorer une répartition nommée, et comment le dire.

    `enrollment_fee_id` est `None` quand le problème porte sur la répartition
    entière et non sur une ligne.
    """

    enrollment_fee_id: int | None
    message: str


def _check_directed_allocations(
    requested: dict[int, Decimal],
    fees_with_paid: list[tuple[EnrollmentFee, Decimal]],
    amount: Decimal,
) -> list[AllocationProblem]:
    """Tout ce qui interdit d'imputer ces montants. Pure, une seule vérité.

    L'aperçu et l'enregistrement posent la même question et doivent recevoir
    la même réponse : l'un l'affiche au caissier pendant qu'il tape, l'autre
    la refuse au moment d'écrire. Deux implémentations finiraient par diverger,
    et l'écran promettrait alors une imputation que la caisse refuse.

    `fees_with_paid` porte **tous** les frais de l'inscription, pas seulement
    ceux qui restent dus : c'est ce qui permet de distinguer un frais déjà
    soldé d'un frais qui n'appartient pas à cette inscription, sans requête
    supplémentaire.

    Un frais d'une autre inscription et un frais qui n'existe pas reçoivent
    sciemment la même phrase. Répondre « introuvable » d'un côté et « pas à
    vous » de l'autre apprendrait à qui essaie quels identifiants existent
    ailleurs, sur un objet qui porte de l'argent.
    """
    problems: list[AllocationProblem] = []

    total = sum(requested.values(), Decimal("0"))
    if total > amount:
        problems.append(
            AllocationProblem(
                None,
                f"La répartition demandée ({total} XOF) dépasse le montant versé "
                f"({amount} XOF). Corrigez la répartition ou le montant encaissé.",
            )
        )

    connus = {fee.id: (fee, paid) for fee, paid in fees_with_paid}
    for fee_id, demande in requested.items():
        connu = connus.get(fee_id)
        if connu is None:
            problems.append(
                AllocationProblem(
                    fee_id,
                    f"Le frais #{fee_id} n'appartient pas à cette inscription : "
                    "aucun versement ne peut y être imputé.",
                )
            )
            continue
        fee, paid = connu
        if not _can_receive_cash(fee, paid):
            problems.append(AllocationProblem(fee_id, _pourquoi_rien_a_recevoir(fee_id, fee)))
            continue
        reste = cash_remaining(fee.status, fee.amount, paid)
        if demande > reste:
            problems.append(
                AllocationProblem(
                    fee_id,
                    f"Le frais #{fee_id} ne peut recevoir que {reste} XOF, or la répartition "
                    f"lui affecte {demande} XOF. On n'impute jamais plus que le reste dû.",
                )
            )
    return problems


def _pourquoi_rien_a_recevoir(fee_id: int, fee: EnrollmentFee) -> str:
    """La phrase à rendre au guichet pour un frais qui n'attend plus d'argent."""
    if is_in_kind(fee.status):
        motif = "a été réglé en nature"
    elif is_not_cash_due(fee.status):
        motif = "est exonéré"
    else:
        motif = "est déjà soldé"
    # Un frais annulé ou dans un état futur tombe ici aussi : « déjà soldé »
    # reste vrai du seul point de vue qui compte au guichet, il n'attend plus
    # d'argent.
    return (
        f"Le frais #{fee_id} {motif} : il n'attend plus d'argent. "
        "Retirez cette ligne de la répartition."
    )


def _plan_split(
    amount: Decimal,
    fees_with_paid: list[tuple[EnrollmentFee, Decimal]],
    requested: dict[int, Decimal] | None = None,
) -> tuple[list[tuple[EnrollmentFee, Decimal]], Decimal]:
    """Impute les montants nommés, puis cascade le reliquat. Pure.

    Sans montant nommé, c'est exactement `_cascade_by_priority` : le reliquat vaut
    alors le versement entier et cascade sur tout. Il n'y a donc pas deux
    façons de répartir, il y en a une, dont la cascade seule est le cas
    particulier. Les appelants n'ont pas à choisir, et ne peuvent pas se
    tromper de fonction.

    `requested` a déjà été passé à `_check_directed_allocations`, qui garantit
    que chaque identifiant désigne un frais de cette liste, encore dû en argent
    et pour un montant tenable. On ne refiltre donc pas ici : écarter en
    silence un identifiant inconnu ferait cascader l'argent que le caissier
    avait nommé, c'est-à-dire réinterpréterait son instruction sans le dire.
    L'invariant est vérifié plutôt que rattrapé.

    Le retour a la même forme que `_cascade_by_priority` : (splits, surplus), un
    seul split par frais, pour que l'écriture des allocations, le recalcul des
    statuts et l'audit ne connaissent qu'un seul chemin quel que soit le mode.

    Le reliquat cascade sur ce qui reste dû **après** les imputations nommées :
    sans ce report, la cascade re-remplirait un frais déjà servi à la main et
    le versement dépasserait la dette.
    """
    nommees = dict(requested or {})
    connus = {fee.id for fee, _ in fees_with_paid}
    inconnus = nommees.keys() - connus
    if inconnus:
        raise AssertionError(f"imputations non verifiees sur les frais {sorted(inconnus)}")

    reliquat = amount - sum(nommees.values(), Decimal("0"))

    apres_nommees = [
        (fee, paid + nommees.get(fee.id, Decimal("0"))) for fee, paid in fees_with_paid
    ]
    cascade, surplus = _cascade_by_priority(reliquat, apres_nommees)
    en_cascade = {fee.id: montant for fee, montant in cascade}

    splits: list[tuple[EnrollmentFee, Decimal]] = []
    for fee, _paid in fees_with_paid:
        total = nommees.get(fee.id, Decimal("0")) + en_cascade.get(fee.id, Decimal("0"))
        if total > 0:
            splits.append((fee, total))
    return splits, surplus


@dataclass(frozen=True)
class AllocationOutcome:
    """Ce qu'il advient d'un versement : ce qui est demandé, refusé, réparti."""

    #: Les montants nommés par le caissier, une entrée par frais après
    #: regroupement des lignes en double.
    directed: dict[int, Decimal]
    #: Vide si la répartition est honorable. Non vide, `splits` est vide.
    problems: list[AllocationProblem]
    splits: list[tuple[EnrollmentFee, Decimal]]
    surplus: Decimal


def resolve_allocation(
    amount: Decimal,
    fees_with_paid: list[tuple[EnrollmentFee, Decimal]],
    allocations: Iterable[tuple[int, Decimal]] = (),
) -> AllocationOutcome:
    """Décide où va ce versement. Seule porte, pour l'aperçu comme pour la caisse.

    Les trois gestes vont ensemble et dans cet ordre : regrouper les lignes qui
    visent le même frais, vérifier ce qui en découle, puis seulement répartir.
    Ils sont privés pour cette raison : appelés séparément, un jour l'un des
    appelants vérifierait avant de regrouper, et opposerait alors le plafond
    d'un frais à la moitié de ce qui lui est demandé.

    Quand la répartition est refusée, rien n'est réparti et rien ne déborde :
    ni `splits`, ni `surplus`. Montrer une ventilation que la caisse refuserait
    ferait croire qu'il suffit de valider.

    `fees_with_paid` porte **tous** les frais de l'inscription : c'est ce qui
    permet de distinguer un frais déjà soldé d'un frais qui n'appartient pas à
    cette inscription. Ceux qui peuvent réellement recevoir sont dérivés ici.
    """
    directed = _merge_directed_lines(allocations)
    problems = _check_directed_allocations(directed, fees_with_paid, amount)
    if problems:
        return AllocationOutcome(directed, problems, [], Decimal("0"))

    splits, surplus = _plan_split(amount, plannable_fees(fees_with_paid), directed)
    return AllocationOutcome(directed, [], splits, surplus)


async def paid_for_fees(db: AsyncSession, fees: Iterable[EnrollmentFee]) -> dict[int, Decimal]:
    """Ce qui est versé sur chacun de ces frais, indexé par frais.

    Une requête groupée par inscription — en pratique une seule, puisque les
    allocations d'un versement portent toutes sur la même. Le calcul est celui
    de `fees_paid`, le seul : la caisse ne peut pas voir un montant que la
    famille ne voit pas sur son portail.
    """
    verses: dict[int, Decimal] = {}
    for enrollment_id in {fee.enrollment_id for fee in fees}:
        verses.update(await fees_paid.paid_by_enrollment(db, enrollment_id))
    return verses


def recompute_fee_status(fee: EnrollmentFee, total_paid: Decimal) -> None:
    """Recalcule le status d'un EnrollmentFee à partir de ce qui y est versé.

    Pure : l'appelant fournit le total, obtenu par `paid_for_fees` en une
    requête pour toute l'inscription. La fonction interrogeait auparavant la
    base elle-même, frais par frais — dans une boucle sur les splits d'un
    versement, cela faisait un aller-retour par frais alors qu'un seul suffit.

    Idempotent : appelable après create, validate ou cancel sans état préalable.
    """
    if is_not_cash_due(fee.status):
        return
    if total_paid >= fee.amount:
        fee.status = EnrollmentFeeStatus.PAID.value
    elif total_paid > Decimal("0"):
        fee.status = EnrollmentFeeStatus.PARTIAL.value
    else:
        fee.status = EnrollmentFeeStatus.PENDING.value
