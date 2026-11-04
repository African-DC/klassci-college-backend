"""Les contraintes de la migration 0091, sur le MySQL de la CI.

La CI applique toutes les migrations sur une vraie base MySQL avant de lancer
pytest. Ce test y insère deux lignes identiques par table, clés étrangères
suspendues le temps de la transaction, puis annule tout : il vérifie que MySQL
refuse la seconde ligne, sous le nom de contrainte que les messages attendent.

En CI, il tourne toujours. Ailleurs, il faut le demander (`RUN_MYSQL_TESTS=1`)
et lui donner une base migrée : une base MySQL quelconque ne suffit pas.
"""

import os
from collections.abc import Iterator
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from app.core.db_errors import integrity_error_message
from app.models.attendance import AttendanceContext, AttendanceRecord, TeacherSessionAttendance

URL = os.environ.get("DATABASE_URL", "")
DEMANDE = os.environ.get("CI") == "true" or os.environ.get("RUN_MYSQL_TESTS") == "1"

pytestmark = pytest.mark.skipif(
    not DEMANDE, reason="base MySQL migrée : en CI, ou sur demande avec RUN_MYSQL_TESTS=1"
)

JOUR = date(2026, 11, 2)
LIGNES = {
    "teacher_session_attendance": {
        "teacher_id": 1,
        "slot_id": 5,
        "date": JOUR,
        "academic_year_id": 1,
        "declared_by_user_id": 1,
        "declared_at": datetime(2026, 11, 2, 8, 0),
    },
    "attendance_contexts": {
        "entity_type": "class",
        "context_id": 3,
        "date": JOUR,
        "academic_year_id": 1,
    },
    "attendance_records": {"context_id": 1, "student_id": 10},
}
TABLES = {
    "teacher_session_attendance": TeacherSessionAttendance.__table__,
    "attendance_contexts": AttendanceContext.__table__,
    "attendance_records": AttendanceRecord.__table__,
}
CONTRAINTES = {
    "teacher_session_attendance": "uq_teacher_attendance_slot_date",
    "attendance_contexts": "uq_attendance_context_day",
    "attendance_records": "uq_attendance_record_student",
}


@pytest.fixture
def conn() -> Iterator[Connection]:
    assert URL.startswith("mysql") and "{tenant}" not in URL, (
        "DATABASE_URL doit viser la base MySQL migrée, sans {tenant}"
    )
    moteur = create_engine(URL.replace("+aiomysql", "+pymysql"))
    try:
        with moteur.connect() as connexion:
            transaction = connexion.begin()
            connexion.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            try:
                yield connexion
            finally:
                transaction.rollback()
                connexion.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    finally:
        moteur.dispose()


@pytest.mark.parametrize("table", sorted(LIGNES))
def test_mysql_refuse_la_seconde_ligne_identique(conn: Connection, table: str) -> None:
    insertion = TABLES[table].insert()
    conn.execute(insertion, LIGNES[table])
    point = conn.begin_nested()

    with pytest.raises(IntegrityError) as erreur:
        conn.execute(insertion, LIGNES[table])
    point.rollback()

    assert CONTRAINTES[table] in str(erreur.value.orig)
    status, detail, code = integrity_error_message(erreur.value)
    assert (status, code) == (409, "DUPLICATE")
    assert "Cet enregistrement existe déjà" not in detail, "message générique au lieu du sien"


def test_mysql_laisse_passer_deux_absences_sans_creneau(conn: Connection) -> None:
    insertion = TeacherSessionAttendance.__table__.insert()
    sans_creneau = {**LIGNES["teacher_session_attendance"], "slot_id": None}

    conn.execute(insertion, sans_creneau)
    conn.execute(insertion, sans_creneau)

    compte = conn.execute(
        text(
            "SELECT COUNT(*) FROM teacher_session_attendance "
            "WHERE teacher_id = 1 AND slot_id IS NULL AND date = :jour"
        ),
        {"jour": JOUR},
    ).scalar()
    assert compte == 2
