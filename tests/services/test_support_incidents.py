"""Dossiers d'incident : visibilité par auteur, réponses, rattachement par code.

Vraie session asynchrone sur SQLite en mémoire : ce qui est lu est ce qui est
enregistré. Chaque règle d'accès est exercée par un appel réel au service.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.support_incident import SupportIncident
from app.schemas.support_incident import IncidentCreate, IncidentReply, IncidentUpdate
from app.services import support_incidents as service

AUTEUR, AUTRE = 7, 8
TABLES = ("support_incidents", "support_incident_events")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    moteur = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    miroir = MetaData()
    Table("users", miroir, Column("id", Integer, primary_key=True))
    for nom in TABLES:
        Base.metadata.tables[nom].to_metadata(miroir)
    # SQLite ne fait autoincrémenter que les INTEGER : on aligne la clé de test.
    miroir.tables["support_incident_events"].c.id.type = Integer()
    async with moteur.begin() as conn:
        await conn.run_sync(lambda c: miroir.create_all(c))
    async with AsyncSession(moteur, expire_on_commit=False) as db:
        yield db
    await moteur.dispose()


def _demande(titre: str = "Bulletin introuvable", reference: str | None = None) -> IncidentCreate:
    return IncidentCreate(
        title=titre,
        description="Le bulletin de la classe 6e A ne s'affiche plus.",
        reference=reference,
    )


async def test_author_sees_only_own_incidents(session: AsyncSession) -> None:
    await service.create(session, _demande("Premier dossier"), actor_id=AUTEUR)
    await service.create(session, _demande("Dossier d'un autre"), actor_id=AUTRE)

    mes_dossiers = await service.list_page(
        session, actor_id=AUTEUR, reference=None, status=None, page=1, size=20
    )
    tous = await service.list_page(
        session, actor_id=None, reference=None, status=None, page=1, size=20
    )

    assert [item.title for item in mes_dossiers.items] == ["Premier dossier"]
    assert tous.total == 2


async def test_other_user_cannot_open_an_incident(session: AsyncSession) -> None:
    dossier = await service.create(session, _demande(), actor_id=AUTEUR)

    with pytest.raises(NotFoundError):
        await service.get(session, dossier.id, actor_id=AUTRE)
    assert (await service.get(session, dossier.id, actor_id=AUTEUR)).id == dossier.id


async def test_reporter_cannot_reply_on_a_dossier_that_is_not_theirs(
    session: AsyncSession,
) -> None:
    dossier = await service.create(session, _demande(), actor_id=AUTEUR)

    with pytest.raises(NotFoundError):
        await service.reply(
            session,
            dossier.id,
            IncidentReply(message="Je suis aussi concerné"),
            actor_id=AUTRE,
            actor_kind="school",
            owner_only=True,
        )


async def test_closed_incident_refuses_replies(session: AsyncSession) -> None:
    dossier = await service.create(session, _demande(), actor_id=AUTEUR)
    await service.update(session, dossier.id, IncidentUpdate(status="closed"))

    with pytest.raises(PermissionDeniedError):
        await service.reply(
            session,
            dossier.id,
            IncidentReply(message="Toujours là"),
            actor_id=AUTEUR,
            actor_kind="school",
            owner_only=True,
        )


async def test_school_reply_reopens_a_waiting_incident(session: AsyncSession) -> None:
    dossier = await service.create(session, _demande(), actor_id=AUTEUR)
    await service.update(session, dossier.id, IncidentUpdate(status="waiting"))

    apres = await service.reply(
        session,
        dossier.id,
        IncidentReply(message="Voici la capture demandée"),
        actor_id=AUTEUR,
        actor_kind="school",
        owner_only=True,
    )

    assert apres.status == "in_progress"
    assert [event.message for event in apres.events][-1] == "Voici la capture demandée"


async def test_report_with_a_backend_reference_joins_the_captured_dossier(
    session: AsyncSession,
) -> None:
    session.add(
        SupportIncident(
            id="b" * 32,
            reference="AB12CD",
            title="Erreur serveur",
            description="Incident détecté automatiquement",
            source="backend",
            status="new",
            priority="high",
        )
    )
    await session.commit()

    dossier = await service.create(
        session, _demande("Je venais de valider", reference="ab12cd"), actor_id=AUTEUR
    )

    assert dossier.id == "b" * 32
    assert dossier.reference == "AB12CD"
    assert dossier.title == "Je venais de valider"
