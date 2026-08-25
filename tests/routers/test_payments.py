"""Tests des endpoints /payments."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.payment import PaymentListResponse, PaymentResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)

SAMPLE_PAYMENT = PaymentResponse(
    id=1,
    enrollment_id=4,
    enrollment_fee_id=10,
    amount=Decimal("50000.00"),
    method="cash",
    status="completed",
    reference=None,
    received_by=1,
    notes=None,
    created_at=NOW,
    updated_at=NOW,
    allocations=[],
)

SAMPLE_LIST = PaymentListResponse(
    items=[SAMPLE_PAYMENT],
    total=1,
    page=1,
    size=20,
)

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")


def _override_deps() -> None:
    """Surcharge les dépendances d'auth et DB pour les tests."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /payments
# ---------------------------------------------------------------------------


def test_list_payments_success() -> None:
    """GET /payments → 200 + liste paginée."""
    _override_deps()
    try:
        with patch(
            "app.routers.payments.payment_service.list_payments",
            new_callable=AsyncMock,
            return_value=SAMPLE_LIST,
        ):
            with TestClient(app) as client:
                resp = client.get("/payments")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["size"] == 20
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == 1


def test_list_payments_with_filters() -> None:
    """GET /payments?status=completed&method=cash → filtrés."""
    _override_deps()
    try:
        with patch(
            "app.routers.payments.payment_service.list_payments",
            new_callable=AsyncMock,
            return_value=SAMPLE_LIST,
        ) as mock_list:
            with TestClient(app) as client:
                resp = client.get(
                    "/payments?status=completed&method=cash&enrollment_fee_id=10&page=2&size=10"
                )
    finally:
        _clear_deps()

    assert resp.status_code == 200
    mock_list.assert_called_once()
    call_kwargs = mock_list.call_args.kwargs
    criteres = call_kwargs["filters"]
    assert criteres.status == "completed"
    assert criteres.method == "cash"
    assert criteres.enrollment_fee_id == 10
    assert call_kwargs["page"] == 2
    assert call_kwargs["size"] == 10


def test_list_payments_unauthenticated() -> None:
    """GET /payments sans token → 401."""
    with TestClient(app) as client:
        resp = client.get("/payments")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /payments
# ---------------------------------------------------------------------------


def test_create_payment_success() -> None:
    """POST /payments → 201 + payment créé."""
    _override_deps()
    try:
        with patch(
            "app.routers.payments.payment_service.create_payment",
            new_callable=AsyncMock,
            return_value=SAMPLE_PAYMENT,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/payments",
                    json={
                        "enrollment_fee_id": 10,
                        "amount": "50000.00",
                        "method": "cash",
                    },
                )
    finally:
        _clear_deps()

    assert resp.status_code == 201
    assert resp.json()["id"] == 1
    assert resp.json()["status"] == "completed"


def test_create_payment_invalid_amount() -> None:
    """POST /payments avec montant négatif → 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/payments",
                json={
                    "enrollment_fee_id": 10,
                    "amount": "-100",
                    "method": "cash",
                },
            )
    finally:
        _clear_deps()

    assert resp.status_code == 422


def test_create_payment_invalid_method() -> None:
    """POST /payments avec méthode invalide → 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/payments",
                json={
                    "enrollment_fee_id": 10,
                    "amount": "50000",
                    "method": "bitcoin",
                },
            )
    finally:
        _clear_deps()

    assert resp.status_code == 422


def test_create_payment_missing_field() -> None:
    """POST /payments sans amount → 422."""
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/payments",
                json={"enrollment_fee_id": 10, "method": "cash"},
            )
    finally:
        _clear_deps()

    assert resp.status_code == 422


def test_create_payment_fee_already_paid() -> None:
    """POST /payments sur un fee déjà payé → 422."""
    from app.core.exceptions import BusinessValidationError

    _override_deps()
    try:
        with patch(
            "app.routers.payments.payment_service.create_payment",
            new_callable=AsyncMock,
            side_effect=BusinessValidationError(
                "Cannot add payment: enrollment fee status is 'paid'"
            ),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/payments",
                    json={
                        "enrollment_fee_id": 10,
                        "amount": "50000",
                        "method": "cash",
                    },
                )
    finally:
        _clear_deps()

    assert resp.status_code == 422


def test_create_payment_exceeds_balance() -> None:
    """POST /payments avec montant > solde restant → 422."""
    from app.core.exceptions import BusinessValidationError

    _override_deps()
    try:
        with patch(
            "app.routers.payments.payment_service.create_payment",
            new_callable=AsyncMock,
            side_effect=BusinessValidationError(
                "Payment amount 999999 exceeds remaining balance 50000"
            ),
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/payments",
                    json={
                        "enrollment_fee_id": 10,
                        "amount": "999999",
                        "method": "cash",
                    },
                )
    finally:
        _clear_deps()

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /payments/{id}
# ---------------------------------------------------------------------------


def test_get_payment_success() -> None:
    """GET /payments/1 → 200 + payment."""
    _override_deps()
    try:
        with patch(
            "app.routers.payments.payment_service.get_payment",
            new_callable=AsyncMock,
            return_value=SAMPLE_PAYMENT,
        ):
            with TestClient(app) as client:
                resp = client.get("/payments/1")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json()["id"] == 1
    assert resp.json()["method"] == "cash"


def test_get_payment_not_found() -> None:
    """GET /payments/999 → 404."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.payments.payment_service.get_payment",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Payment", 999),
        ):
            with TestClient(app) as client:
                resp = client.get("/payments/999")
    finally:
        _clear_deps()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /payments/student/{enrollment_id}
# ---------------------------------------------------------------------------


def test_get_student_payments_success() -> None:
    """GET /payments/student/42 → 200 + liste de paiements."""
    _override_deps()
    try:
        with patch(
            "app.routers.payments.payment_service.get_student_payments",
            new_callable=AsyncMock,
            return_value=[SAMPLE_PAYMENT],
        ):
            with TestClient(app) as client:
                resp = client.get("/payments/student/42")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["id"] == 1


def test_get_student_payments_empty() -> None:
    """GET /payments/student/42 sans paiements → 200 + liste vide."""
    _override_deps()
    try:
        with patch(
            "app.routers.payments.payment_service.get_student_payments",
            new_callable=AsyncMock,
            return_value=[],
        ):
            with TestClient(app) as client:
                resp = client.get("/payments/student/42")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    assert resp.json() == []
