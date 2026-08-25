"""Suppression en cascade : dire ce qu'on emporte, refuser ce qui compte.

Deux règles, une seule fois écrites, valables pour toute la configuration :

1. **Ce qui n'a servi à personne s'efface**, avec ce qui en dépend, une fois
   l'utilisateur informé du compte exact.
2. **Ce qui porte de l'argent ou des élèves ne s'efface pas.** Un versement
   encaissé qui perd sa contrepartie est un trou comptable que le journal
   d'audit ne rattrapera pas, et une classe supprimée sous ses inscrits
   emporte leurs frais avec elle.

Le refus lui-même porte l'inventaire : le premier clic sur Supprimer répond
409 avec le décompte, l'écran l'affiche, et l'utilisateur confirme en
connaissance de cause. Un second endpoint d'aperçu dirait la même chose
depuis un autre code, et les deux finiraient par diverger.
"""

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True, slots=True)
class Dependent:
    """Une catégorie de choses qui dépendent de l'élément à supprimer.

    Les deux formes sont fournies plutôt que déduites : « frais d'élève »
    donne « frais d'élèves », pas « frais d'élèves » en ajoutant un `s` à
    chaque mot, et « montant configuré » en prend deux. Le français a trop
    d'exceptions pour qu'on les devine, et un « 1 montants configurés » à
    l'écran d'une école se remarque.
    """

    singular: str
    plural: str
    count: int
    #: `True` quand l'existence de ces éléments interdit la suppression,
    #: même confirmée.
    blocking: bool = False

    @property
    def label(self) -> str:
        return self.singular if self.count == 1 else self.plural

    def phrase(self) -> str:
        return f"{self.count} {self.label}"


@dataclass(frozen=True, slots=True)
class DeletionPlan:
    """Ce qu'emporterait la suppression, et ce qui l'interdit."""

    entity_label: str
    dependents: tuple[Dependent, ...]

    @property
    def blockers(self) -> tuple[Dependent, ...]:
        return tuple(d for d in self.dependents if d.blocking and d.count)

    @property
    def collateral(self) -> tuple[Dependent, ...]:
        return tuple(d for d in self.dependents if not d.blocking and d.count)

    def as_payload(self) -> list[dict[str, object]]:
        return [
            {"label": d.label, "count": d.count, "blocking": d.blocking}
            for d in self.dependents
            if d.count
        ]


def _total(dependents: tuple[Dependent, ...]) -> int:
    return sum(d.count for d in dependents)


def _join(phrases: list[str]) -> str:
    if len(phrases) == 1:
        return phrases[0]
    return ", ".join(phrases[:-1]) + " et " + phrases[-1]


def ensure_deletable(plan: DeletionPlan, *, cascade: bool) -> None:
    """Laisse passer, ou refuse en 409 avec l'inventaire.

    Trois issues :

    - rien ne dépend de l'élément → on supprime ;
    - quelque chose de bloquant en dépend → refus définitif, la cascade n'y
      change rien ;
    - des éléments non utilisés en dépendent → refus la première fois avec
      le décompte, acceptation si l'utilisateur confirme.
    """
    if plan.blockers:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DELETE_BLOCKED",
                "message": (
                    f"Impossible de supprimer {plan.entity_label} : "
                    f"{_join([d.phrase() for d in plan.blockers])} "
                    f"{'en dépend' if _total(plan.blockers) == 1 else 'en dépendent'}. "
                    "Ces données ne peuvent pas être détruites."
                ),
                "dependents": plan.as_payload(),
                "can_cascade": False,
            },
        )

    if plan.collateral and not cascade:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DELETE_HAS_DEPENDENTS",
                "message": (
                    f"Supprimer {plan.entity_label} entraînera aussi la suppression de "
                    f"{_join([d.phrase() for d in plan.collateral])}. Confirmez pour continuer."
                ),
                "dependents": plan.as_payload(),
                "can_cascade": True,
            },
        )
