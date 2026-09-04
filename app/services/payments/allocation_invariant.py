"""La somme des allocations vaut exactement le versement — et c'est vérifié.

Cet invariant n'était qu'une phrase de docstring sur `PaymentAllocation`. Or
tout le point par catégorie repose dessus : `fee_category_ledger` ne lit QUE la
table des allocations, jamais `Payment.amount`. Un versement dont les
allocations manqueraient, ou ne couvriraient pas son montant, sortirait de tous
les totaux par catégorie **sans qu'aucun signal ne le dise** — le journal de
caisse continuerait, lui, de le compter, et deux chiffres justes qui divergent
sans explication détruisent la confiance dans les deux.

Un commentaire n'est pas un mécanisme. L'invariant est donc tenu par trois
choses qui se répondent :

1. **Une contrainte unique en base** — `uq_payment_allocation` sur
   `(payment_id, enrollment_fee_id)`, posée par la migration 0079. Deux lignes
   pour le même frais sur le même versement s'additionnaient jusqu'ici sans que
   rien ne dise pourquoi elles étaient deux.
2. **Une vérification à l'écriture** — `verifier`, appelée par les DEUX chemins
   d'enregistrement avant d'écrire quoi que ce soit. Rien n'est enregistré
   quand la ventilation ne couvre pas le versement : un versement à moitié
   ventilé est pire qu'un versement refusé, parce qu'il se lit comme complet.
3. **Un contrôle a posteriori** — `auditer`, en lecture seule, que la commande
   `python -m app.cli.check_allocations` passe sur chaque base.

Les trois jugent par la MÊME fonction pure, `inspecter`. Deux règles pour une
seule question finiraient par se contredire : l'audit passerait ce que la
caisse refuse, et on chercherait le défaut dans la base au lieu du code.

## L'écart toléré

Un demi-centime. Les montants sont des `Numeric(15, 2)` en francs CFA et la
répartition n'a pas de division : l'écart légitime est nul. La tolérance
n'existe que pour ne pas transformer un arrondi de moteur en incident, et elle
est trop étroite pour laisser passer le moindre franc.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AllocationInvariantError

#: L'écart au-delà duquel la ventilation ne couvre plus le versement. Un demi
#: centime : il n'y a pas d'arrondi légitime dans cette addition.
ECART_TOLERE = Decimal("0.005")


@dataclass(frozen=True, slots=True)
class RuptureInvariant:
    """Un versement dont la ventilation ne dit pas ce que le versement dit.

    Porté par la vérification d'écriture comme par l'audit : les deux décrivent
    le même défaut, et doivent le nommer avec les mêmes mots.
    """

    #: `None` à l'écriture — le versement n'a pas encore d'identifiant.
    payment_id: int | None
    #: Ce que la caisse a reçu.
    montant: Decimal
    #: Ce que les allocations totalisent.
    alloue: Decimal
    #: Les frais visés plus d'une fois par ce versement. Ils s'additionnent en
    #: silence, et rien ne dit pourquoi ils sont deux.
    frais_en_double: tuple[int, ...]

    @property
    def ecart(self) -> Decimal:
        """Ce qui manque à la ventilation. Négatif, elle déborde."""
        return self.montant - self.alloue

    @property
    def sans_allocation(self) -> bool:
        """Vrai quand rien n'a été ventilé du tout : le cas le plus grave.

        Le versement est alors invisible de bout en bout du point par
        catégorie, alors qu'il figure au journal de caisse.
        """
        return self.alloue == Decimal("0")

    def message(self) -> str:
        """Ce qu'on écrit à quelqu'un qui doit agir dessus."""
        qui = f"Versement {self.payment_id}" if self.payment_id is not None else "Ce versement"
        if self.frais_en_double:
            frais = ", ".join(str(identifiant) for identifiant in self.frais_en_double)
            return (
                f"{qui} : le même frais est visé plusieurs fois "
                f"(frais {frais}). Deux lignes pour un frais s'additionnent "
                f"sans que rien ne dise pourquoi elles sont deux."
            )
        if self.sans_allocation:
            return (
                f"{qui} de {self.montant} XOF n'est ventilé sur aucun frais. "
                f"Il figure au journal de caisse et manque à tous les points "
                f"par catégorie."
            )
        return (
            f"{qui} : {self.montant} XOF reçus, {self.alloue} XOF ventilés, "
            f"soit {self.ecart} XOF que le point par catégorie ne verra jamais."
        )


def inspecter(
    montant: Decimal,
    splits: Iterable[tuple[int, Decimal]],
    *,
    payment_id: int | None = None,
) -> RuptureInvariant | None:
    """La règle, écrite une seule fois. `None` quand la ventilation est saine.

    Pure : elle ne connaît ni base ni session. C'est ce qui permet au chemin
    d'écriture de la poser AVANT d'écrire — sur ce qu'il s'apprête à écrire —
    et à l'audit de la poser APRÈS, sur ce qui a été écrit, en obtenant
    exactement le même verdict.

    `splits` porte des couples (frais, montant). Un frais nommé deux fois est
    un défaut à lui seul, même si la somme tombe juste : c'est ce que la
    contrainte unique refuse désormais en base, et la nommer ici permet de le
    dire avec des mots plutôt qu'avec un numéro d'erreur MySQL.
    """
    lignes = [(int(frais), Decimal(str(part))) for frais, part in splits]
    alloue = sum((part for _frais, part in lignes), Decimal("0"))

    vus: set[int] = set()
    doubles: list[int] = []
    for frais, _part in lignes:
        if frais in vus and frais not in doubles:
            doubles.append(frais)
        vus.add(frais)

    if not doubles and abs(Decimal(str(montant)) - alloue) <= ECART_TOLERE:
        return None

    return RuptureInvariant(
        payment_id=payment_id,
        montant=Decimal(str(montant)),
        alloue=alloue,
        frais_en_double=tuple(doubles),
    )


def verifier(montant: Decimal, splits: Iterable[tuple[int, Decimal]]) -> None:
    """Refuse d'écrire une ventilation qui ne couvre pas son versement.

    Appelée par les deux chemins d'enregistrement, avant la première écriture.
    L'invariant tenait jusqu'ici par construction — le trop-perçu est refusé en
    amont et la cascade consomme tout le montant — mais « par construction »
    est exactement ce qui cesse d'être vrai le jour où l'on ajoute un troisième
    chemin, ou un cas de répartition partielle. Ce qui manquait n'était pas le
    comportement, c'était le filet.

    L'erreur levée n'est pas une erreur de saisie : la personne au guichet n'a
    rien fait de mal, et le message le dit. La confondre avec un montant mal
    tapé enverrait la caissière corriger une saisie juste.
    """
    rupture = inspecter(montant, splits)
    if rupture is None:
        return
    raise AllocationInvariantError(
        f"{rupture.message()} Le versement n'a pas été enregistré. "
        f"Ce n'est pas une erreur de saisie : signalez-le au support."
    )


async def auditer(db: AsyncSession, *, limite: int = 200) -> list[RuptureInvariant]:
    """Les versements encaissés dont la ventilation ne dit pas la même chose.

    LECTURE SEULE. Le contrôle a posteriori, sur le modèle de la commande
    `frais:verifier-allocations` de KLASSCIv2 : il ne répare rien, il nomme.
    Une réparation automatique choisirait à la place d'un comptable où ranger
    de l'argent réel, et c'est exactement la décision qu'une machine ne doit
    pas prendre seule.

    Seuls les versements `completed` sont regardés : un versement annulé ou en
    attente n'est compté nulle part, ni au journal ni au point par catégorie,
    et sa ventilation n'engage donc rien.

    Le tri se fait en base — une ligne rendue par versement en défaut, aucune
    par versement sain — parce qu'une école tient des dizaines de milliers de
    versements et qu'un audit qui les rapatrie tous ne se lance plus.
    """
    from app.models.fee import Payment, PaymentAllocation, PaymentStatus

    ventilation = (
        select(
            PaymentAllocation.payment_id.label("payment_id"),
            func.coalesce(func.sum(PaymentAllocation.amount), 0).label("alloue"),
            func.count(PaymentAllocation.id).label("lignes"),
            func.count(func.distinct(PaymentAllocation.enrollment_fee_id)).label("frais"),
        )
        .group_by(PaymentAllocation.payment_id)
        .subquery()
    )

    stmt = (
        select(
            Payment.id,
            Payment.amount,
            func.coalesce(ventilation.c.alloue, 0).label("alloue"),
            func.coalesce(ventilation.c.lignes, 0).label("lignes"),
            func.coalesce(ventilation.c.frais, 0).label("frais"),
        )
        .outerjoin(ventilation, ventilation.c.payment_id == Payment.id)
        .where(
            Payment.status == PaymentStatus.COMPLETED.value,
            # Les trois formes du défaut : rien de ventilé, une somme qui
            # s'écarte, ou plus de lignes que de frais visés — le doublon que
            # la contrainte unique refuse désormais, et qui peut précéder sa
            # pose.
            (ventilation.c.alloue.is_(None))
            | (func.abs(Payment.amount - ventilation.c.alloue) > ECART_TOLERE)
            | (ventilation.c.lignes > ventilation.c.frais),
        )
        .order_by(Payment.id)
        .limit(limite)
    )

    lignes = (await db.execute(stmt)).all()
    if not lignes:
        return []

    doubles = await _frais_en_double(db, [int(row.id) for row in lignes])
    return [
        RuptureInvariant(
            payment_id=int(row.id),
            montant=Decimal(str(row.amount or 0)),
            alloue=Decimal(str(row.alloue or 0)),
            frais_en_double=doubles.get(int(row.id), ()),
        )
        for row in lignes
    ]


async def _frais_en_double(
    db: AsyncSession, payment_ids: Sequence[int]
) -> dict[int, tuple[int, ...]]:
    """Quels frais sont visés plusieurs fois, pour les seuls versements signalés.

    Une seconde requête, et volontairement : la nommer dans la première
    obligerait à rapatrier toutes les lignes de tous les versements pour ne
    s'en servir que sur une poignée.
    """
    from app.models.fee import PaymentAllocation

    if not payment_ids:
        return {}

    stmt = (
        select(PaymentAllocation.payment_id, PaymentAllocation.enrollment_fee_id)
        .where(PaymentAllocation.payment_id.in_(list(payment_ids)))
        .group_by(PaymentAllocation.payment_id, PaymentAllocation.enrollment_fee_id)
        .having(func.count(PaymentAllocation.id) > 1)
        .order_by(PaymentAllocation.payment_id, PaymentAllocation.enrollment_fee_id)
    )

    par_versement: dict[int, list[int]] = {}
    for versement, frais in (await db.execute(stmt)).all():
        par_versement.setdefault(int(versement), []).append(int(frais))
    return {versement: tuple(frais) for versement, frais in par_versement.items()}
