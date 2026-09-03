"""Ce qui est entre se cloisonne ; ce qui reste du ne se cloisonne pas.

Le point sur une categorie sert deux metiers a la fois. La caissiere y lit ce
qu'elle a encaisse — un fait sur sa caisse, vrai quel que soit le reste. Le
comptable y lit en plus ce que les familles doivent encore, ce qui se calcule
sur tout l'argent recu.

Melanger les deux serait grave dans les deux sens : refuser son propre point a
la caissiere l'empecherait de travailler ; lui montrer un reste du calcule sur
sa seule caisse lui ferait relancer une famille qui a paye au guichet d'a cote.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.services.fee_category_ledger import CategoryLedger

CAISSIERE = TokenData(user_id=12, tenant_id="local", email="sophie.yao@college.ci")
COMPTABLE = TokenData(user_id=3, tenant_id="local", email="comptable@college.ci")

ROUTE = "/payments/settlement/category?category_id=1&academic_year_id=1"


def _vide(*, consolide: bool) -> CategoryLedger:
    return CategoryLedger(
        category_id=1,
        category_name="PAQUET DE RAM",
        accepts_in_kind=True,
        class_name="Toutes les classes",
        date_from=None,
        date_to=None,
        consolide=consolide,
        eleves_en_argent=0,
        total_en_argent=0,
        depots_en_nature=0,
        eleves_restant_du=0 if consolide else None,
        total_restant_du=0 if consolide else None,
        lignes=(),
    )


def _client(qui: TokenData, *, permissions: set[str]) -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: qui
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()

    async def _check(_db: object, _user_id: int, slug: str) -> bool:
        return slug in permissions

    try:
        with patch("app.repositories.permission_repository.check_user_permission", new=_check):
            yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def caissiere() -> Iterator[TestClient]:
    yield from _client(CAISSIERE, permissions={"payments:read", "payments:create"})


@pytest.fixture
def comptable() -> Iterator[TestClient]:
    yield from _client(COMPTABLE, permissions={"payments:read", "payments:read:all"})


def test_la_caissiere_fait_son_point(caissiere: TestClient) -> None:
    """Ce qu'elle a encaisse sur cette categorie est a elle : on ne le lui refuse pas."""
    with patch(
        "app.routers.payments.fee_category_ledger.load_category_ledger",
        new_callable=AsyncMock,
        return_value=_vide(consolide=False),
    ) as charge:
        reponse = caissiere.get(ROUTE)

    assert reponse.status_code == 200
    # Ramenee a sa propre caisse, meme sans l'avoir demande.
    assert charge.await_args.kwargs["received_by"] == CAISSIERE.user_id
    assert charge.await_args.kwargs["consolide"] is False


def test_le_reste_du_est_absent_et_non_faux_pour_la_caissiere(caissiere: TestClient) -> None:
    """Un reste du calcule sur une seule caisse ferait relancer qui a deja paye."""
    with patch(
        "app.routers.payments.fee_category_ledger.load_category_ledger",
        new_callable=AsyncMock,
        return_value=_vide(consolide=False),
    ):
        corps = caissiere.get(ROUTE).json()

    assert corps["consolide"] is False
    assert corps["total_restant_du"] is None
    assert corps["eleves_restant_du"] is None


def test_un_filtre_de_caisse_ne_sert_pas_de_passe_droit(caissiere: TestClient) -> None:
    """Demander la caisse d'une collegue ne l'ouvre pas."""
    with patch(
        "app.routers.payments.fee_category_ledger.load_category_ledger",
        new_callable=AsyncMock,
        return_value=_vide(consolide=False),
    ) as charge:
        caissiere.get(f"{ROUTE}&received_by=99")

    assert charge.await_args.kwargs["received_by"] == CAISSIERE.user_id


def test_le_comptable_lit_toutes_les_caisses_et_le_du(comptable: TestClient) -> None:
    with patch(
        "app.routers.payments.fee_category_ledger.load_category_ledger",
        new_callable=AsyncMock,
        return_value=_vide(consolide=True),
    ) as charge:
        corps = comptable.get(ROUTE).json()

    assert charge.await_args.kwargs["received_by"] is None
    assert charge.await_args.kwargs["consolide"] is True
    assert corps["consolide"] is True
    assert corps["total_restant_du"] is not None


def test_sans_droit_de_lecture_des_paiements_la_porte_est_fermee() -> None:
    for client in _client(CAISSIERE, permissions=set()):
        assert client.get(ROUTE).status_code == 403
        break
