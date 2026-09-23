"""Tests de audit_log — résilience aux erreurs DB et re-raise des erreurs critiques."""

from unittest.mock import AsyncMock

import pytest
import sqlalchemy.exc

from app.core.audit import AuditAction, audit_log


def _mock_db() -> AsyncMock:
    """Retourne une session AsyncSession simulée."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_happy_path() -> None:
    """audit_log s'exécute sans erreur sur une session saine."""
    db = _mock_db()
    await audit_log(db, entity_type="enrollment", action=AuditAction.CREATE, entity_id=1)
    db.execute.assert_awaited_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_audit_log_ne_fait_jamais_de_requete_de_confort() -> None:
    """Une seule requête : l'insertion. Jamais de lecture pour nommer le sujet.

    Cette fonction est appelée dans des boucles — un import de huit cents
    élèves, une levée de zéros d'office sur une classe entière. Une requête
    ajoutée ici pour le confort d'affichage y devient une requête par ligne.
    Le nom vient de l'objet que le service tient déjà.
    """
    db = _mock_db()
    for entity_type in ("student", "payment", "grade", "enrollment"):
        db.execute.reset_mock()
        await audit_log(db, entity_type=entity_type, action=AuditAction.UPDATE, entity_id=1)
        assert db.execute.await_count == 1, entity_type


# ---------------------------------------------------------------------------
# Résilience — erreurs DB swallowées
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_swallows_db_operational_error() -> None:
    """Une erreur opérationnelle DB (timeout, connexion perdue) est swallowée."""
    db = _mock_db()
    db.execute.side_effect = sqlalchemy.exc.OperationalError("stmt", {}, Exception("timeout"))

    # Ne doit pas propager — la requête principale continue
    await audit_log(db, entity_type="payment", action=AuditAction.CREATE, entity_id=42)


@pytest.mark.asyncio
async def test_audit_log_swallows_integrity_error() -> None:
    """Une IntegrityError sur la table audit est swallowée."""
    db = _mock_db()
    db.flush.side_effect = sqlalchemy.exc.IntegrityError("stmt", {}, Exception("duplicate"))

    await audit_log(db, entity_type="grade", action=AuditAction.UPDATE, entity_id=5)


# ---------------------------------------------------------------------------
# Erreurs critiques — re-raised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_log_reraises_invalid_request_error() -> None:
    """InvalidRequestError (session corrompue) doit être propagée."""
    db = _mock_db()
    db.execute.side_effect = sqlalchemy.exc.InvalidRequestError("session closed")

    with pytest.raises(sqlalchemy.exc.InvalidRequestError):
        await audit_log(db, entity_type="enrollment", action=AuditAction.DELETE, entity_id=1)


@pytest.mark.asyncio
async def test_audit_log_reraises_type_error() -> None:
    """TypeError (erreur de programmation) doit être propagée."""
    db = _mock_db()
    db.execute.side_effect = TypeError("bad argument")

    with pytest.raises(TypeError):
        await audit_log(db, entity_type="enrollment", action=AuditAction.CREATE, entity_id=1)
