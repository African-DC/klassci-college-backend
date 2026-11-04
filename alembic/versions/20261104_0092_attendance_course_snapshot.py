"""Teacher attendance keeps its course — revision 0092.

Régénérer l'emploi du temps supprime les créneaux générés de la classe et en
crée de nouveaux. `teacher_session_attendance.slot_id` passait alors à NULL
(`ondelete="SET NULL"`) et le pointage ne disait plus de quel cours il
s'agissait : sur la base `recette550` de la démo, régénérée le 2026-11-01, les
800 pointages ont tous perdu leur créneau.

Le pointage porte désormais la classe, la matière et l'horaire du cours pointé,
recopiés du créneau au moment de la saisie. Le créneau reste le plan ; le
pointage garde ce qui s'est passé, même si le plan change ensuite.

Reprise : les pointages encore liés à un créneau reçoivent la copie de ce
créneau. Ceux dont le créneau a déjà disparu restent sans cours : l'information
n'existe plus nulle part en base. Aucune base de production n'en contient
(aucun pointage au 2026-11-04).

Revision ID: 0092_attendance_course_snapshot
Revises: 0091_attendance_uniqueness
"""

import sqlalchemy as sa

from alembic import op

revision = "0092_attendance_course_snapshot"
down_revision = "0091_attendance_uniqueness"
branch_labels = None
depends_on = None

TABLE = "teacher_session_attendance"

# (colonne, type SQL, table référencée ou None)
COLUMNS = (
    ("class_id", sa.BigInteger(), "classes"),
    ("subject_id", sa.BigInteger(), "subjects"),
    ("planned_start", sa.Time(), None),
    ("planned_end", sa.Time(), None),
)

# colonne du pointage → colonne du créneau
SNAPSHOT = (
    ("class_id", "class_id"),
    ("subject_id", "subject_id"),
    ("planned_start", "start_time"),
    ("planned_end", "end_time"),
)


def _existing_columns(bind: sa.engine.Connection) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(TABLE)}


def _existing_indexes(bind: sa.engine.Connection) -> set[str]:
    return {i["name"] for i in sa.inspect(bind).get_indexes(TABLE)}


def _existing_foreign_keys(bind: sa.engine.Connection) -> set[str]:
    return {fk["name"] for fk in sa.inspect(bind).get_foreign_keys(TABLE)}


def _fk_name(column: str) -> str:
    return f"fk_teacher_attendance_{column}"


def _index_name(column: str) -> str:
    return f"ix_teacher_session_attendance_{column}"


def upgrade():
    """Chaque étape est vérifiée à part : le DDL MySQL n'est pas transactionnel,
    et une exécution interrompue doit pouvoir reprendre là où elle s'est arrêtée."""
    bind = op.get_bind()
    columns = _existing_columns(bind)
    for name, type_, _ in COLUMNS:
        if name not in columns:
            op.add_column(TABLE, sa.Column(name, type_, nullable=True))

    # L'index avant la clé étrangère : MySQL le réutilise au lieu d'en créer un second.
    indexes = _existing_indexes(bind)
    foreign_keys = _existing_foreign_keys(bind)
    for name, _, target in COLUMNS:
        if target is None:
            continue
        if _index_name(name) not in indexes:
            op.create_index(_index_name(name), TABLE, [name])
        if _fk_name(name) not in foreign_keys:
            op.create_foreign_key(
                _fk_name(name), TABLE, target, [name], ["id"], ondelete="RESTRICT"
            )

    copy_course_from_slot(bind)


def copy_course_from_slot(bind: sa.engine.Connection) -> int:
    """Recopie le cours du créneau sur chaque pointage qui y est encore lié.

    Sous-requêtes corrélées : la même instruction vaut pour MySQL et SQLite.
    Un pointage déjà renseigné n'est pas réécrit.
    """
    assignments = ", ".join(
        f"{mine} = (SELECT s.{theirs} FROM timetable_slots s WHERE s.id = {TABLE}.slot_id)"
        for mine, theirs in SNAPSHOT
    )
    result = bind.execute(
        sa.text(f"UPDATE {TABLE} SET {assignments} WHERE slot_id IS NOT NULL AND class_id IS NULL")
    )
    return int(result.rowcount or 0)


def downgrade():
    bind = op.get_bind()
    foreign_keys = _existing_foreign_keys(bind)
    indexes = _existing_indexes(bind)
    columns = _existing_columns(bind)
    for name, _, target in reversed(COLUMNS):
        if target is not None:
            if _fk_name(name) in foreign_keys:
                op.drop_constraint(_fk_name(name), TABLE, type_="foreignkey")
            if _index_name(name) in indexes:
                op.drop_index(_index_name(name), table_name=TABLE)
        if name in columns:
            op.drop_column(TABLE, name)
