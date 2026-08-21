"""Les routes de telechargement des portails, du chemin appele au code rendu.

Les tests de service voisins couvrent la regle d'acces. Ceux-ci verifient ce
qui n'existe qu'au niveau du routeur : le chemin, le type de contenu rendu, et
surtout le code de refus — 404 et non 403.
"""

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from tests.bulletin_portal_decor import (
    CLASSMATE_ID,
    CLASSMATE_PUBLISHED,
    FAKE_PDF,
    OWN_DRAFT,
    OWN_PUBLISHED,
    STUDENT_ID,
    BulletinsDb,
    install_pdf_factory,
    login_parent,
    login_student,
    open_payment_gate,
)

STUDENT_USER = TokenData(user_id=3, tenant_id="local", email="eleve@college.ci")
PARENT_USER = TokenData(user_id=10, tenant_id="local", email="parent@college.ci")


@pytest.fixture(autouse=True)
def portal_decor(monkeypatch) -> None:
    """Fabrique de PDF fictive et porte de paiement ouverte."""
    install_pdf_factory(monkeypatch)
    open_payment_gate(monkeypatch)


@pytest.fixture
def portal_client() -> Generator:
    """Fabrique un client authentifie sur la base reduite aux bulletins."""

    @contextmanager
    def _factory(token: TokenData) -> Generator[TestClient, None, None]:
        app.dependency_overrides[get_current_user] = lambda: token
        app.dependency_overrides[get_tenant_db] = lambda: BulletinsDb()
        app.dependency_overrides[get_redis] = lambda: AsyncMock()
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.clear()

    return _factory


@pytest.fixture
def as_student(monkeypatch) -> None:
    login_student(monkeypatch)


@pytest.fixture
def as_parent(monkeypatch) -> None:
    login_parent(monkeypatch)


# ---------------------------------------------------------------------------
# GET /student/bulletins/{bulletin_id}/pdf
# ---------------------------------------------------------------------------


def test_eleve_recoit_son_bulletin_en_pdf(portal_client, as_student) -> None:
    """200 + application/pdf, sans jamais demander `reports:read`."""
    with portal_client(STUDENT_USER) as client:
        resp = client.get(f"/student/bulletins/{OWN_PUBLISHED}/pdf")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == FAKE_PDF


def test_eleve_recoit_404_sur_le_bulletin_d_un_camarade(portal_client, as_student) -> None:
    """404 et non 403 : un 403 confirmerait que l'identifiant existe."""
    with portal_client(STUDENT_USER) as client:
        resp = client.get(f"/student/bulletins/{CLASSMATE_PUBLISHED}/pdf")

    assert resp.status_code == 404


def test_eleve_recoit_404_sur_un_bulletin_non_publie(portal_client, as_student) -> None:
    """Le portail ne montre que le publie ; le telechargement suit la meme regle."""
    with portal_client(STUDENT_USER) as client:
        resp = client.get(f"/student/bulletins/{OWN_DRAFT}/pdf")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /parent/children/{student_id}/bulletins/{bulletin_id}/pdf
# ---------------------------------------------------------------------------


def test_parent_recoit_le_bulletin_de_son_enfant(portal_client, as_parent) -> None:
    """200 + application/pdf sur l'enfant rattache."""
    with portal_client(PARENT_USER) as client:
        resp = client.get(f"/parent/children/{STUDENT_ID}/bulletins/{OWN_PUBLISHED}/pdf")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == FAKE_PDF


def test_parent_recoit_404_sur_l_enfant_d_une_autre_famille(portal_client, as_parent) -> None:
    """404 sur un enfant non rattache — l'identifiant reste muet."""
    with portal_client(PARENT_USER) as client:
        resp = client.get(f"/parent/children/{CLASSMATE_ID}/bulletins/{CLASSMATE_PUBLISHED}/pdf")

    assert resp.status_code == 404


def test_parent_recoit_404_sur_un_bulletin_non_publie(portal_client, as_parent) -> None:
    """Le brouillon de son propre enfant reste hors du portail."""
    with portal_client(PARENT_USER) as client:
        resp = client.get(f"/parent/children/{STUDENT_ID}/bulletins/{OWN_DRAFT}/pdf")

    assert resp.status_code == 404
