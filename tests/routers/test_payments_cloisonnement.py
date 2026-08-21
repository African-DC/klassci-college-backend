"""Le cloisonnement de la caisse, à l'écran comme à l'export.

Un caissier lit sa caisse et rien d'autre. La liste le respectait déjà ; ces
tests vérifient qu'un export ne sert pas de porte dérobée — c'est le genre de
fuite qu'on ne voit jamais en regardant l'interface, parce qu'elle sort dans un
fichier que personne ne rouvre pour compter les lignes.

Les tests passent par les endpoints réels, avec la matrice de permissions
branchée sur des réponses contrôlées : c'est le vrai chemin de décision, pas
une relecture de son intention.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.models.fee import Payment
from app.repositories.payment_filters import PaymentFilters, apply_payment_filters
from app.schemas.payment import (
    CashierOption,
    PaymentListResponse,
    PaymentResponse,
)
from app.services.payments.scope import cashier_scope

CAISSIERE = TokenData(user_id=12, tenant_id="local", email="sophie.yao@college.ci")
COMPTABLE = TokenData(user_id=3, tenant_id="local", email="comptable@college.ci")

MAINTENANT = datetime.now(UTC)

VERSEMENT = PaymentResponse(
    id=1,
    enrollment_id=4,
    amount=Decimal("50000.00"),
    method="cash",
    status="completed",
    reference="REC-0141",
    received_by=12,
    received_by_name="Sophie Yao",
    notes=None,
    created_at=MAINTENANT,
    updated_at=MAINTENANT,
    allocations=[],
)

UNE_PAGE = PaymentListResponse(items=[VERSEMENT], total=1, page=1, size=20)


def _client(qui: TokenData, *, permissions: set[str]) -> Iterator[TestClient]:
    """Client authentifié dont la matrice de permissions répond `permissions`."""
    app.dependency_overrides[get_current_user] = lambda: qui
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()

    async def _check(_db: object, _user_id: int, slug: str) -> bool:
        return slug in permissions

    try:
        with patch(
            "app.repositories.permission_repository.check_user_permission",
            new=_check,
        ):
            yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def caissiere() -> Iterator[TestClient]:
    """Caissière : `payments:read` sans `payments:read:all`, comme la matrice."""
    yield from _client(CAISSIERE, permissions={"payments:read", "payments:create"})


@pytest.fixture
def sans_droit() -> Iterator[TestClient]:
    """Compte authentifié mais dépourvu de `payments:read`."""
    yield from _client(CAISSIERE, permissions=set())


@pytest.fixture
def comptable() -> Iterator[TestClient]:
    yield from _client(
        COMPTABLE, permissions={"payments:read", "payments:read:all", "payments:create"}
    )


# ---------------------------------------------------------------------------
# La règle, seule
# ---------------------------------------------------------------------------


def test_sans_le_droit_global_on_est_ramene_a_sa_caisse() -> None:
    assert cashier_scope(requested_received_by=None, can_read_all=False, current_user_id=12) == 12


def test_un_filtre_ne_sert_pas_de_passe_droit() -> None:
    """Demander explicitement la caisse d'un collègue ne l'ouvre pas."""
    assert cashier_scope(requested_received_by=99, can_read_all=False, current_user_id=12) == 12


def test_avec_le_droit_global_on_lit_tout_ou_ce_qu_on_demande() -> None:
    assert cashier_scope(requested_received_by=None, can_read_all=True, current_user_id=3) is None
    assert cashier_scope(requested_received_by=99, can_read_all=True, current_user_id=3) == 99


# ---------------------------------------------------------------------------
# La requête
# ---------------------------------------------------------------------------


def _sql(filtres: PaymentFilters) -> str:
    """Le SQL réellement produit pour ces critères."""
    requete = apply_payment_filters(select(Payment), filtres)
    return str(requete.compile(compile_kwargs={"literal_binds": True}))


def test_le_cloisonnement_descend_jusque_dans_la_requete() -> None:
    """Filtrer en Python après coup laisserait le total et la pagination
    compter les versements des collègues."""
    assert "payments.received_by = 12" in _sql(PaymentFilters(received_by=12))


def test_sans_cloisonnement_la_requete_ne_borne_pas_la_caisse() -> None:
    assert "WHERE" not in _sql(PaymentFilters())


def test_la_periode_descend_aussi_dans_la_requete() -> None:
    """Un filtre de date appliqué côté navigateur ne verrait que la page
    courante : le document sorti derrière serait faux."""
    sql = _sql(
        PaymentFilters(
            date_from=datetime(2026, 9, 1, 0, 0, 0),
            date_to=datetime(2026, 9, 30, 23, 59, 59),
        )
    )
    assert "payments.created_at >=" in sql
    assert "payments.created_at <=" in sql


# ---------------------------------------------------------------------------
# L'écran
# ---------------------------------------------------------------------------


def test_la_liste_d_une_caissiere_est_bornee_a_sa_caisse(caissiere: TestClient) -> None:
    with patch(
        "app.routers.payments.payment_service.list_payments",
        new_callable=AsyncMock,
        return_value=UNE_PAGE,
    ) as liste:
        reponse = caissiere.get("/payments")

    assert reponse.status_code == 200
    assert liste.call_args.kwargs["received_by"] == CAISSIERE.user_id


def test_une_caissiere_ne_peut_pas_demander_la_caisse_d_une_collegue(
    caissiere: TestClient,
) -> None:
    with patch(
        "app.routers.payments.payment_service.list_payments",
        new_callable=AsyncMock,
        return_value=UNE_PAGE,
    ) as liste:
        reponse = caissiere.get("/payments?received_by=999")

    assert reponse.status_code == 200
    assert liste.call_args.kwargs["received_by"] == CAISSIERE.user_id


def test_le_comptable_lit_toutes_les_caisses(comptable: TestClient) -> None:
    with patch(
        "app.routers.payments.payment_service.list_payments",
        new_callable=AsyncMock,
        return_value=UNE_PAGE,
    ) as liste:
        reponse = comptable.get("/payments")

    assert reponse.status_code == 200
    assert liste.call_args.kwargs["received_by"] is None


def test_le_comptable_peut_isoler_la_caisse_d_une_personne(comptable: TestClient) -> None:
    with patch(
        "app.routers.payments.payment_service.list_payments",
        new_callable=AsyncMock,
        return_value=UNE_PAGE,
    ) as liste:
        reponse = comptable.get("/payments?received_by=12")

    assert reponse.status_code == 200
    assert liste.call_args.kwargs["received_by"] == 12


def test_la_liste_nomme_qui_a_encaisse(comptable: TestClient) -> None:
    """Le nom voyage jusqu'à l'écran : sans lui, la colonne resterait vide."""
    with patch(
        "app.routers.payments.payment_service.list_payments",
        new_callable=AsyncMock,
        return_value=UNE_PAGE,
    ):
        reponse = comptable.get("/payments")

    assert reponse.json()["items"][0]["received_by_name"] == "Sophie Yao"


# ---------------------------------------------------------------------------
# Les exports
# ---------------------------------------------------------------------------


def _filtres_de(appel: AsyncMock):
    return appel.call_args.kwargs["filters"]


def test_l_export_pdf_d_une_caissiere_est_borne_a_sa_caisse(caissiere: TestClient) -> None:
    with patch(
        "app.routers.payments.payments_journal_service.get_journal_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-1.7 test",
    ) as export:
        reponse = caissiere.get("/payments/export?format=pdf")

    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "application/pdf"
    assert _filtres_de(export).received_by == CAISSIERE.user_id
    assert export.call_args.kwargs["restricted"] is True


def test_l_export_excel_d_une_caissiere_est_borne_a_sa_caisse(caissiere: TestClient) -> None:
    with patch(
        "app.routers.payments.payments_journal_service.get_journal_xlsx",
        new_callable=AsyncMock,
        return_value=b"PK\x03\x04",
    ) as export:
        reponse = caissiere.get("/payments/export?format=xlsx")

    assert reponse.status_code == 200
    assert _filtres_de(export).received_by == CAISSIERE.user_id


def test_l_export_ne_contourne_pas_le_cloisonnement_par_son_parametre(
    caissiere: TestClient,
) -> None:
    """Le paramètre qui sert au comptable à isoler une caisse ne doit pas
    devenir, pour la caissière, le moyen d'ouvrir celle des autres."""
    with patch(
        "app.routers.payments.payments_journal_service.get_journal_xlsx",
        new_callable=AsyncMock,
        return_value=b"PK\x03\x04",
    ) as export:
        reponse = caissiere.get("/payments/export?format=xlsx&received_by=999")

    assert reponse.status_code == 200
    assert _filtres_de(export).received_by == CAISSIERE.user_id


def test_l_export_du_comptable_couvre_toutes_les_caisses(comptable: TestClient) -> None:
    with patch(
        "app.routers.payments.payments_journal_service.get_journal_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-1.7 test",
    ) as export:
        reponse = comptable.get("/payments/export")

    assert reponse.status_code == 200
    assert _filtres_de(export).received_by is None
    assert export.call_args.kwargs["restricted"] is False


def test_l_export_reprend_les_filtres_de_l_ecran(comptable: TestClient) -> None:
    with patch(
        "app.routers.payments.payments_journal_service.get_journal_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-1.7 test",
    ) as export:
        reponse = comptable.get(
            "/payments/export"
            "?status=completed&method=cash"
            "&date_from=2026-09-01T00:00:00&date_to=2026-09-30T23:59:59"
        )

    assert reponse.status_code == 200
    filtres = _filtres_de(export)
    assert filtres.status == "completed"
    assert filtres.method == "cash"
    assert filtres.date_from == datetime(2026, 9, 1, 0, 0, 0)
    assert filtres.date_to == datetime(2026, 9, 30, 23, 59, 59)


def test_un_format_inconnu_est_refuse(comptable: TestClient) -> None:
    assert comptable.get("/payments/export?format=docx").status_code == 422


def test_l_export_exige_le_droit_de_lire_les_versements(sans_droit: TestClient) -> None:
    assert sans_droit.get("/payments/export").status_code == 403


def test_la_liste_des_encaisseurs_exige_le_meme_droit(sans_droit: TestClient) -> None:
    assert sans_droit.get("/payments/cashiers").status_code == 403


# ---------------------------------------------------------------------------
# La liste des encaisseurs
# ---------------------------------------------------------------------------


def test_une_caissiere_ne_voit_qu_elle_meme_dans_le_filtre(caissiere: TestClient) -> None:
    """Lui servir la liste de ses collègues lui apprendrait qui tient les
    autres guichets, pour un filtre qui ne pourrait rien lui montrer d'eux."""
    with patch(
        "app.routers.payments.payments_journal_service.own_cashier_option",
        new_callable=AsyncMock,
        return_value=[CashierOption(id=12, name="Sophie Yao")],
    ) as propre:
        with patch(
            "app.routers.payments.payments_journal_service.list_cashier_options",
            new_callable=AsyncMock,
        ) as toutes:
            reponse = caissiere.get("/payments/cashiers")

    assert reponse.status_code == 200
    assert reponse.json() == [{"id": 12, "name": "Sophie Yao"}]
    propre.assert_awaited_once()
    toutes.assert_not_awaited()


def test_le_comptable_voit_tous_les_encaisseurs(comptable: TestClient) -> None:
    with patch(
        "app.routers.payments.payments_journal_service.list_cashier_options",
        new_callable=AsyncMock,
        return_value=[
            CashierOption(id=12, name="Sophie Yao"),
            CashierOption(id=18, name="Mariam Diallo"),
        ],
    ):
        reponse = comptable.get("/payments/cashiers")

    assert reponse.status_code == 200
    assert [option["name"] for option in reponse.json()] == ["Sophie Yao", "Mariam Diallo"]
