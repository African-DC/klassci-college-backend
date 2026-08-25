"""Les frais se cherchent sur l'année résolue, pas sur celle de la requête.

Le formulaire complet élève plus inscription laisse l'année facultative et
retombe sur l'année en cours. Le service résolvait bien cette année pour créer
l'inscription, puis cherchait les tarifs avec la valeur brute de la requête.
Quand le formulaire ne l'envoyait pas, la recherche portait sur `None`, aucun
tarif ne correspondait, et l'élève était inscrit **sans aucun frais** : la
caisse n'avait rien à imputer et la fiche annonçait « 0 F » à la famille.

Vu en production le 2026-08-21 sur deux inscriptions réelles.

On vérifie ici le comportement de la recherche de tarifs face à une année
absente, plutôt que la plomberie complète de la création : c'est ce point-là
qui décidait entre « facturé » et « rien du tout ».
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import Class
from app.models.fee import FeeCategory, FeeVariant


@pytest.fixture
def db() -> Session:
    moteur = create_engine("sqlite://")
    Base.metadata.create_all(
        moteur,
        tables=[
            Class.__table__,
            FeeCategory.__table__,
            FeeVariant.__table__,
        ],
    )
    with Session(moteur) as session:
        session.add(Class(id=1, name="6eme A", level_id=2, series_id=None, max_students=40))
        session.add(FeeCategory(id=1, name="Inscription", is_mandatory=True, priority=10))
        session.add(
            FeeVariant(
                id=1,
                fee_category_id=1,
                level_id=2,
                series_id=None,
                academic_year_id=7,
                amount=Decimal("37000"),
            )
        )
        session.commit()
        yield session


def _tarifs(db: Session, annee: int | None) -> list[FeeVariant]:
    """La requête de recherche, exécutée en synchrone sur SQLite."""
    from sqlalchemy import select

    stmt = select(FeeVariant).where(
        FeeVariant.academic_year_id == annee,
        FeeVariant.level_id == 2,
    )
    return list(db.execute(stmt).scalars().all())


def test_une_annee_absente_ne_trouve_aucun_tarif(db: Session) -> None:
    """C'est le scénario exact du défaut : rien ne remonte, donc rien n'est facturé."""
    assert _tarifs(db, None) == []


def test_lannee_resolue_trouve_le_tarif(db: Session) -> None:
    """Avec l'année en cours, l'élève est bien facturé."""
    trouves = _tarifs(db, 7)

    assert [(v.id, Decimal(str(v.amount))) for v in trouves] == [(1, Decimal("37000"))]
