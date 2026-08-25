"""Une notification diffusée doit survivre à la requête.

`dispatch_notification` fait `add` puis `flush`, ce qui ouvre une transaction
sans la valider. Les deux appelants de la chaîne d'inscription s'exécutent
**après** le commit métier ; `get_db` referme ensuite la session sans jamais
recommiter, et la fermeture annule la transaction. Résultat : l'inscription
existait, le versement existait, et la cloche restait vide. Aucune erreur,
aucune trace.

Le test précédent remplaçait `dispatch_notification` pour vérifier le routage.
Il avait donc raison sur qui est prévenu, et ne pouvait rien dire de ce qui
est écrit. Celui-ci compte les lignes après coup.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import BigInteger, create_engine, func, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.notification import (
    Notification,
    NotificationPreference,
)
from app.models.permission import Permission, Role, RolePermission, UserRole
from app.models.user import User
from app.services import notification_dispatch_service as dispatch

ENCAISSER = "payments:create"


class _AsyncBridge:
    """Une `AsyncSession` de facade, qui commite et referme pour de vrai."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.commits = 0

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self.commits += 1
        self._session.commit()


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")

    # SQLite n auto-incremente que les INTEGER PRIMARY KEY, pas les BigInteger
    # que le modele declare pour MySQL. Sans ce rendu, toute insertion sans
    # identifiant explicite echoue sur une contrainte NOT NULL.
    @compiles(BigInteger, "sqlite")
    def _bigint_sqlite(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    # Le schema entier : le service charge les profils lies (enseignant,
    # eleve, parent) et les preferences. Les enumerer un par un rendait le
    # montage fragile a chaque relation ajoutee.
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                User(id=1, email="sophie@ecole.ci", hashed_password="x", role="staff"),
                Role(id=10, name="Secrétaire"),
                Permission(id=100, slug=ENCAISSER, name="Encaisser"),
                RolePermission(role_id=10, permission_id=100),
                UserRole(id=1, user_id=1, role_id=10),
                # SQLite n auto-incremente pas les BigInteger : sans identifiant
                # explicite, la creation a la volee de la preference echoue.
                NotificationPreference(id=1, user_id=1, email=False, sms=False),
            ]
        )
        session.commit()
        yield session


@pytest.mark.asyncio
async def test_la_notification_est_bien_ecrite(db: Session) -> None:
    pont = _AsyncBridge(db)
    envoyees = await dispatch.dispatch_to_permission(
        pont,
        ENCAISSER,
        "enrollment_awaiting_payment",
        {"title": "Versement attendu", "body": "…"},
        action_url="/admin/enrollments/42?action=encaisser",
        entity_type="enrollment",
        entity_id=42,
    )
    assert len(envoyees) == 1
    # Le point du test : la ligne existe encore une fois la requete finie.
    assert pont.commits == 1
    compte = db.execute(select(func.count()).select_from(Notification)).scalar()
    assert compte == 1


@pytest.mark.asyncio
async def test_la_notification_ecrite_porte_sa_destination(db: Session) -> None:
    pont = _AsyncBridge(db)
    await dispatch.dispatch_to_permission(
        pont,
        ENCAISSER,
        "enrollment_awaiting_payment",
        {"title": "Versement attendu", "body": "…"},
        action_url="/admin/enrollments/42?action=encaisser",
        entity_type="enrollment",
        entity_id=42,
    )
    ligne = db.execute(select(Notification)).scalar_one()
    assert ligne.action_url == "/admin/enrollments/42?action=encaisser"
    assert ligne.read is False


@pytest.mark.asyncio
async def test_sans_destinataire_on_ne_commite_pas(db: Session) -> None:
    pont = _AsyncBridge(db)
    envoyees = await dispatch.dispatch_to_permission(
        pont, "permission:inexistante", "system", {"title": "x", "body": "y"}
    )
    # Rien a ecrire : on ne valide pas une transaction vide, qui pourrait
    # confirmer au passage un travail en cours chez l'appelant.
    assert envoyees == []
    assert pont.commits == 0
