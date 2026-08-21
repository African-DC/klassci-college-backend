"""Le courriel de trace doit nommer l'auteur de la suppression.

C'est toute la valeur du message : le chef d'établissement apprend qu'une fiche
a disparu **et par qui**. « Utilisateur 12 » suffirait à peine ; un courriel qui
ne part pas du tout ne sert à rien.

Or le nom de l'auteur se lit sur son profil, une relation du compte. Tant que
cette relation n'était pas chargée dans la requête, la lire déclenchait un
aller-retour vers la base au mauvais moment : sous le moteur asynchrone de
l'application, un tel chargement différé lève, et l'appelant — qui a pour
consigne de ne jamais faire échouer une suppression à cause d'un courriel —
avalait l'exception. La fiche partait, personne n'était prévenu, et seule une
ligne de journal en gardait la trace.

Le test reproduit cette contrainte sans pilote asynchrone : la session rend des
objets **détachés**, c'est-à-dire hors d'état de faire la moindre requête
supplémentaire, exactement comme le moteur asynchrone l'impose au milieu d'un
`await`.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import BigInteger, Integer, MetaData, create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401  — enregistre toutes les tables sur `Base`
from app.core.database import Base
from app.models.user import StaffProfile, TeacherProfile, User
from app.services import deletion_notice_service as notice
from app.services.archive_service import ArchiveOutcome

SECRETAIRE = 12
ENSEIGNANT = 13
SANS_PROFIL = 14


class _DetachedBridge:
    """Une session qui rend des objets incapables de requêter à nouveau.

    C'est la contrainte réelle du moteur asynchrone, transposée : ce qui n'a
    pas été demandé dans la requête n'est plus accessible ensuite.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    async def execute(self, statement: Any) -> Any:
        frozen = self.session.execute(statement).freeze()
        self.session.expunge_all()
        return frozen()


def _sqlite_schema() -> MetaData:
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)
    for table in miroir.tables.values():
        for column in table.columns:
            if isinstance(column.type, BigInteger):
                column.type = Integer()
    return miroir


def _compte(user_id: int, email: str, role: str) -> User:
    return User(
        id=user_id,
        email=email,
        hashed_password="peu-importe",
        role=role,
        is_active=True,
        must_change_password=False,
    )


@pytest.fixture
def db() -> Iterator[_DetachedBridge]:
    """Trois comptes : une secrétaire, un enseignant, un compte sans profil."""
    engine = create_engine("sqlite://")
    _sqlite_schema().create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                _compte(SECRETAIRE, "sophie.yao@college.ci", "admin"),
                _compte(ENSEIGNANT, "aissatou.diallo@college.ci", "teacher"),
                _compte(SANS_PROFIL, "console@college.ci", "admin"),
                StaffProfile(user_id=SECRETAIRE, first_name="Sophie", last_name="Yao"),
                TeacherProfile(user_id=ENSEIGNANT, first_name="Aissatou", last_name="Diallo"),
            ]
        )
        session.flush()
        yield _DetachedBridge(session)

    engine.dispose()


@pytest.mark.asyncio
async def test_le_courriel_nomme_la_secretaire_qui_a_supprime(db: _DetachedBridge) -> None:
    assert await notice._resolve_actor_name(db, SECRETAIRE) == (  # type: ignore[arg-type]
        "Sophie Yao (sophie.yao@college.ci)"
    )


@pytest.mark.asyncio
async def test_le_courriel_nomme_aussi_un_enseignant(db: _DetachedBridge) -> None:
    """Le profil enseignant est l'autre porteur de nom : il se lit pareil."""
    assert await notice._resolve_actor_name(db, ENSEIGNANT) == (  # type: ignore[arg-type]
        "Aissatou Diallo (aissatou.diallo@college.ci)"
    )


@pytest.mark.asyncio
async def test_un_compte_sans_profil_est_nomme_par_son_adresse(db: _DetachedBridge) -> None:
    """On ne renonce jamais à nommer quelqu'un."""
    assert await notice._resolve_actor_name(db, SANS_PROFIL) == (  # type: ignore[arg-type]
        "console@college.ci"
    )


@pytest.mark.asyncio
async def test_un_auteur_inconnu_de_la_base_reste_identifiable(db: _DetachedBridge) -> None:
    assert await notice._resolve_actor_name(db, 999) == "Utilisateur 999"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_le_courriel_part_vraiment_et_porte_le_nom(
    db: _DetachedBridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le bout du bout : le message remis à la direction nomme la secrétaire.

    Sans chargement anticipé du profil, cette fonction levait avant d'écrire la
    moindre ligne et l'appel rendait `False` sans qu'aucun courriel ne parte.
    """
    from app.services import admin_service

    class _Ecole:
        school_name = "College Saint-Augustin"
        email = "direction@saint-augustin.ci"
        deletion_notice_emails = None
        head_master_name = "Mme Diallo"
        mailpulse_enabled = False
        mailpulse_sender_email = None
        mailpulse_sender_name = None

    remis: list[tuple[str, str, str]] = []

    async def _ecole(_db: Any) -> Any:
        return _Ecole()

    def _envoyer(destinataire: str, sujet: str, html: str, texte: str) -> bool:
        remis.append((destinataire, sujet, texte))
        return True

    monkeypatch.setattr(admin_service, "get_school_settings", _ecole)
    monkeypatch.setattr(notice.email_service, "send_email", _envoyer)

    envoye = await notice.send_deletion_notice(  # type: ignore[arg-type]
        db,
        ArchiveOutcome(
            entity_type="student",
            entity_id=42,
            label="L'élève Traoré Aminata",
            reason="Fiche créée en double lors de la rentrée",
            permanent=True,
            actor_id=SECRETAIRE,
        ),
    )

    assert envoye is True
    assert len(remis) == 1
    destinataire, _sujet, texte = remis[0]
    assert destinataire == "direction@saint-augustin.ci"
    assert "Sophie Yao" in texte
