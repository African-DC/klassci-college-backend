"""Ce que `audited_update` garantit, et qu'aucune convention ne garantissait.

Le bloc « modifier puis journaliser » existait en douze copies. Une copie qui
oubliait `old_values` s'enregistrait sans erreur : le défaut ne se voyait que
six mois plus tard, devant une famille qui conteste un montant. Ces tests
appellent le helper et regardent ce qu'il transmet au journal.
"""

from typing import Any

import pytest
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.audit import AuditAction
from app.services import audited_crud


class _Base(DeclarativeBase):
    pass


class _Classe(_Base):
    __tablename__ = "classes_de_test"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    max_students: Mapped[int] = mapped_column()


class _SessionFactice:
    """Juste ce dont le helper se sert : un point de reprise."""

    def begin_nested(self) -> "_SessionFactice":
        return self

    async def __aenter__(self) -> "_SessionFactice":
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False


@pytest.fixture
def journal(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    ecrit: list[dict[str, Any]] = []

    async def _capturer(_db: object, **kwargs: Any) -> None:
        ecrit.append(kwargs)

    monkeypatch.setattr(audited_crud, "audit_log", _capturer)
    return ecrit


@pytest.mark.asyncio
async def test_la_modification_laisse_l_avant_l_apres_et_le_nom(
    journal: list[dict[str, Any]],
) -> None:
    classe = _Classe(id=7, name="6e A", max_students=40)
    applique: dict[str, Any] = {}

    async def _updater(_db: object, obj: _Classe, **changes: Any) -> _Classe:
        applique.update(changes)
        for cle, valeur in changes.items():
            setattr(obj, cle, valeur)
        return obj

    await audited_crud.audited_update(
        _SessionFactice(),  # type: ignore[arg-type]
        classe,
        {"name": "6e B", "max_students": 45},
        entity_type="class",
        updater=_updater,
        actor=3,
    )

    assert applique == {"name": "6e B", "max_students": 45}
    assert len(journal) == 1
    ligne = journal[0]
    assert ligne["action"] is AuditAction.UPDATE
    assert ligne["entity_type"] == "class"
    # L'identifiant vient de l'objet modifié, il ne peut pas désigner une
    # autre fiche.
    assert ligne["entity_id"] == 7
    assert ligne["old_values"] == {"name": "6e A", "max_students": 40}
    assert ligne["new_values"] == {"name": "6e B", "max_students": 45}
    # Le nom est celui d'avant, comme la colonne « Avant » juste à côté.
    assert ligne["subject_label"] == "6e A"


@pytest.mark.asyncio
async def test_une_cle_qui_n_est_pas_une_colonne_tombe_avant_d_ecrire(
    journal: list[dict[str, Any]],
) -> None:
    """Le service doit retirer lui-même ce qui ne lui appartient pas.

    `update_room` en donne l'exemple : son payload porte `class_id`, qui vit
    sur `Class`. Mieux vaut tomber ici qu'écrire la moitié des champs.
    """
    classe = _Classe(id=7, name="6e A", max_students=40)

    async def _updater(_db: object, _obj: _Classe, **_changes: Any) -> None:
        raise AssertionError("on ne doit pas arriver jusqu'a l'ecriture")

    with pytest.raises(AttributeError, match="room_id"):
        await audited_crud.audited_update(
            _SessionFactice(),  # type: ignore[arg-type]
            classe,
            {"name": "6e B", "room_id": 3},
            entity_type="class",
            updater=_updater,
            actor=3,
        )

    assert journal == []
