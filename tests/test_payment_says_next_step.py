"""Le versement dit si l'inscription reste à valider.

Un champ déclaré dans le schéma et jamais renseigné par l'assembleur répond
toujours `False`. Rien ne le signale : le code compile, les tests passent, et
l'écran croit simplement qu'il n'y a plus rien à faire.

`PaymentResponse` se construit par arguments explicites, pas par
`model_validate` : ajouter le champ au schéma ne suffit donc pas, contrairement
aux notifications où `from_attributes` fait le travail. Ce test lit la réponse
que l'assembleur produit vraiment.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.enrollment import EnrollmentStatus
from app.services.payments._response import payment_to_response


def _versement(statut_inscription: object | None) -> object:
    inscription = (
        None
        if statut_inscription is None
        else SimpleNamespace(id=4, status=statut_inscription, student=None)
    )
    return SimpleNamespace(
        id=1,
        enrollment_id=4,
        enrollment_fee_id=None,
        amount=Decimal("3000"),
        method="cash",
        status="completed",
        reference=None,
        received_by=1,
        received_by_user=None,
        notes=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        cancelled_at=None,
        cancelled_by=None,
        cancelled_by_user=None,
        cancellation_reason=None,
        enrollment=inscription,
        allocations=[],
        enrollment_fee=None,
        student_name_snapshot=None,
        student_matricule_snapshot=None,
    )


@pytest.mark.parametrize(
    ("statut", "attendu"),
    [
        (EnrollmentStatus.PROSPECT, True),
        (EnrollmentStatus.EN_VALIDATION, True),
        (EnrollmentStatus.VALIDE, False),
    ],
)
def test_le_versement_dit_si_l_inscription_attend_encore(statut, attendu) -> None:
    reponse = payment_to_response(_versement(statut))
    assert reponse.enrollment_awaiting_validation is attendu


def test_sans_inscription_chargee_on_ne_promet_rien() -> None:
    # Plutot qu'un lazy-load hors greenlet, qui rendrait un 500 sur
    # l'encaissement pour un simple libelle d'ecran.
    reponse = payment_to_response(_versement(None))
    assert reponse.enrollment_awaiting_validation is False
