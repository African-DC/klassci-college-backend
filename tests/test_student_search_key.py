"""La clé de recherche d'un élève, tenue par le modèle à chaque écriture.

Ce fichier garde le chemin d'ÉCRITURE. La détection elle-même — ce que la
recherche ramène — est gardée par `test_duplicate_detection.py`. Les deux
étaient mélangés, et le test d'écriture y passait pour une raison de lecture.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.user import Student


@pytest.fixture()
def session() -> Iterator[Session]:
    """Un seul élève, celui qu'on va renommer. Rien d'autre n'est nécessaire ici."""
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    with Session(moteur) as s:
        s.add(Student(last_name="KOUASSI", first_name="David", enrollment_number="ECER0864"))
        s.commit()
        yield s


def test_la_cle_est_posee_a_la_creation() -> None:
    """Un élève neuf porte sa forme comparable sans que l'appelant y pense."""
    eleve = Student(last_name="N’GUESSAN", first_name="Marie-Line")
    assert eleve.last_name_key == "nguessan"
    assert eleve.first_name_key == "marieline"


def test_la_cle_suit_la_correction_d_un_nom(session: Session) -> None:
    """La forme comparable suit la correction d'un nom, sans que personne y pense.

    Le secrétariat corrige une faute de saisie des semaines après l'inscription.
    Si la clé restait sur l'ancienne orthographe, l'élève deviendrait
    introuvable sous son vrai nom : on le recréerait, avec une seconde ardoise
    que personne ne rapprocherait de la première.

    La clé est lue EN BASE après le commit. Une version antérieure se contentait
    de rechercher l'élève après l'avoir renommé : elle passait aussi avec une
    clé de nom périmée, parce que le prénom suffisait à ramener la fiche. Elle
    gardait donc la lecture, pas l'écriture.
    """
    eleve = session.query(Student).filter(Student.enrollment_number == "ECER0864").one()
    assert eleve.last_name_key == "kouassi", "la fixture doit partir d'une clé connue"

    eleve.last_name = "N’GUESSAN"
    session.commit()

    stockee = session.execute(
        select(Student.last_name_key).where(Student.id == eleve.id)
    ).scalar_one()
    assert stockee == "nguessan", (
        "la clé stockée doit suivre le nom corrigé, apostrophe courbe comprise"
    )
