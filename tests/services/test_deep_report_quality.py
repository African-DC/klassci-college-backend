"""Colonne « Qualité » du rapport DEEP : saisie d'abord, déduction seulement si permise.

Avant, une seule inscription antérieure en base suffisait à déduire : tous les
élèves sans ligne ressaisie passaient « Non Red », alors que l'école n'avait
jamais déclaré son historique complet.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.services.deep_report._context import load_context
from tests.services._sheet_world import (
    AN_COURANT,
    AN_PASSE,
    CLASSE_3E,
    CLASSE_4E,
    AsyncBridge,
    add_enrollment,
    add_student,
    build_school,
)


@pytest.fixture()
def ecole(request: pytest.FixtureRequest) -> Iterator[Session]:
    """`request.param` dit si l'école a déclaré son historique exploitable."""
    for session in build_school(history_reliable=request.param):
        add_student(session, 1, "Koné", "Awa")
        add_student(session, 2, "Yao", "Paul")
        add_student(session, 3, "Diallo", "Inès")
        add_enrollment(session, 10, 1, CLASSE_4E, AN_PASSE)
        add_enrollment(session, 11, 1, CLASSE_4E, AN_COURANT)  # même niveau : redouble
        add_enrollment(session, 12, 2, CLASSE_3E, AN_COURANT)  # aucune trace l'an passé
        add_enrollment(session, 13, 3, CLASSE_3E, AN_COURANT, is_repeater=True)  # saisi
        session.commit()
        yield session


async def _qualites(session: Session) -> dict[int, bool | None]:
    contexte = await load_context(AsyncBridge(session), AN_COURANT, 1)  # type: ignore[arg-type]
    return {line.enrollment.id: line.is_repeater for line in contexte.lines}


@pytest.mark.asyncio
@pytest.mark.parametrize("ecole", [False], indirect=True)
async def test_historique_non_declare_rien_n_est_deduit(ecole: Session) -> None:
    qualites = await _qualites(ecole)

    assert qualites == {11: None, 12: None, 13: True}


@pytest.mark.asyncio
@pytest.mark.parametrize("ecole", [True], indirect=True)
async def test_historique_declare_la_deduction_complete_la_saisie(ecole: Session) -> None:
    qualites = await _qualites(ecole)

    assert qualites == {11: True, 12: False, 13: True}
