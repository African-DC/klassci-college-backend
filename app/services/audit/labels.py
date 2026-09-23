"""Mettre des noms sur une page du journal, pour un lecteur humain.

Deux sources, dans cet ordre :

1. Le nom **figé à l'écriture** (`subject_label`) : c'est le nom qu'avait la
   fiche au moment de l'acte, et il survit à sa suppression.
2. À défaut, le **nom actuel** de la fiche, lu ici, par lot. C'est ce qui
   nomme les lignes écrites avant la migration 0082, les créations, les
   consultations, et toutes les actions dont le service ne passe pas encore de
   nom. Une fiche renommée depuis s'affiche sous son nom d'aujourd'hui : c'est
   un nom, ce n'est pas un faux, et c'est ce qui permet de s'y retrouver.

Les identifiants cités dans les valeurs (`level_id: 3`) sont traduits de la
même façon, et rendus **par champ** : `"level_id:3" → "6e"`. L'écran n'a pas à
savoir que `slot_id` désigne un créneau ; il lit le nom sous la clé qu'il a
déjà en main.

Le cloisonnement suit celui des lignes. Un type que le lecteur ne voit pas
dans le journal n'est pas nommé dans les valeurs s'il désigne une personne :
sans cette limite, un comptable lirait, à travers un `teacher_id` rangé dans
une valeur, un nom que son périmètre ne lui ouvre pas.

Coût : une requête par type d'entité présent sur la page, une dizaine au plus
pour cinquante lignes. Jamais une par ligne.
"""

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog
from app.repositories import audit_labels as repo
from app.repositories.audit_labels import Fiche

#: Clé d'une valeur de journal → type d'entité qu'elle désigne.
CLES_IDENTIFIANTS: dict[str, str] = {
    "academic_year_id": "academic_year",
    "class_id": "class",
    "enrollment_fee_id": "enrollment_fee",
    "enrollment_id": "enrollment",
    "evaluation_id": "evaluation",
    "fee_category_id": "fee_category",
    "level_id": "level",
    "optional_fee_option_id": "optional_fee_option",
    "parent_id": "parent",
    "role_id": "role",
    "room_id": "room",
    "series_id": "series",
    "slot_id": "timetable_slot",
    "student_id": "student",
    "subject_id": "subject",
    "teacher_id": "teacher",
}

EtatFiche = Literal["active", "archived", "deleted"]


def _parcourir(valeur: Any) -> Iterator[tuple[str, Any]]:
    """Toutes les paires `(clé, valeur)`, y compris dans une répartition."""
    if isinstance(valeur, dict):
        for cle, sous in valeur.items():
            yield str(cle), sous
            yield from _parcourir(sous)
    elif isinstance(valeur, list):
        for element in valeur:
            yield from _parcourir(element)


def _nommable(entity_type: str, allowed: frozenset[str] | None) -> bool:
    spec = repo.LIBELLES.get(entity_type)
    if spec is None:
        return False
    return allowed is None or entity_type in allowed or not spec.personnel


def _identifiants(row: AuditLog, allowed: frozenset[str] | None) -> Iterator[tuple[str, str, int]]:
    """`(clé, type, id)` des identifiants nommables cités par une ligne."""
    for bloc in (row.old_values, row.new_values):
        for cle, valeur in _parcourir(bloc):
            entity_type = CLES_IDENTIFIANTS.get(cle)
            if entity_type is None or isinstance(valeur, bool) or not isinstance(valeur, int):
                continue
            if _nommable(entity_type, allowed):
                yield cle, entity_type, valeur


def _regrouper(paires: Iterable[tuple[str, int]]) -> dict[str, set[int]]:
    groupes: dict[str, set[int]] = {}
    for entity_type, entity_id in paires:
        groupes.setdefault(entity_type, set()).add(entity_id)
    return groupes


@dataclass(frozen=True, slots=True)
class RowLabels:
    """Ce que l'écran affiche d'une ligne, au lieu de ses numéros."""

    nom: str | None
    #: `None` quand le type n'a pas de fiche à retrouver.
    etat: EtatFiche | None
    #: `"clé:id"` → nom, pour chaque identifiant cité dans les valeurs.
    valeurs: dict[str, str]


class PageLabels:
    """Les noms d'une page, lus en une requête par type."""

    def __init__(self, trouve: dict[str, dict[int, Fiche]], allowed: frozenset[str] | None) -> None:
        self._trouve = trouve
        self._allowed = allowed

    def _fiche(self, entity_type: str, entity_id: int) -> Fiche | None:
        return self._trouve.get(entity_type, {}).get(entity_id)

    def de(self, row: AuditLog) -> RowLabels:
        etat: EtatFiche | None = None
        fiche = None
        if row.entity_id is not None and row.entity_type in self._trouve:
            fiche = self._fiche(row.entity_type, row.entity_id)
            if fiche is None:
                etat = "deleted"
            else:
                etat = "archived" if fiche.archivee else "active"

        valeurs: dict[str, str] = {}
        for cle, entity_type, entity_id in _identifiants(row, self._allowed):
            cite = self._fiche(entity_type, entity_id)
            if cite is not None and cite.nom:
                valeurs[f"{cle}:{entity_id}"] = cite.nom

        return RowLabels(
            nom=row.subject_label or (fiche.nom if fiche else None),
            etat=etat,
            valeurs=valeurs,
        )


async def page_labels(
    db: AsyncSession, rows: Sequence[AuditLog], *, allowed: frozenset[str] | None
) -> PageLabels:
    """Nomme les fiches d'une page, en une requête par type d'entité.

    `allowed` est le périmètre du lecteur, tel que `_scope` le décide :
    `None` pour l'accès complet.
    """
    sujets = {
        (row.entity_type, row.entity_id)
        for row in rows
        if row.entity_id is not None and row.entity_type in repo.LIBELLES
    }
    cites = {(t, i) for row in rows for _, t, i in _identifiants(row, allowed)}
    trouve = await repo.names_by_type(db, _regrouper(sujets | cites))
    # Un type cherché mais sans réponse (requête en échec) ne doit pas faire
    # dire « fiche supprimée » : il reste absent de `trouve`, donc sans état.
    return PageLabels(trouve, allowed)
