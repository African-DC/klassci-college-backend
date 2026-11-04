"""Attendance uniqueness — revision 0091, one row per natural key.

Un pointage par (enseignant, créneau, date), un appel par (classe ou examen,
date), une ligne par élève dans un appel. Le service vérifiait le premier
avant d'insérer, mais deux requêtes simultanées passaient toutes les deux ; les
deux autres n'étaient vérifiés nulle part.

Rien n'est dédoublonné ici. Le rapport du 2026-11-04 n'a trouvé aucun doublon
en production (rostan-bouake, local) ni sur la démo (local, recette550, demo2).
Si une base en contient malgré tout, la migration s'arrête et dit où : choisir
la ligne à garder est une décision métier, pas un effet de bord de migration.

Revision ID: 0091_attendance_uniqueness
Revises: 0090_schedule_events
"""

import sqlalchemy as sa

from alembic import op

revision = "0091_attendance_uniqueness"
down_revision = "0090_schedule_events"
branch_labels = None
depends_on = None

# (nom de contrainte, table, colonnes, libellé pour le message d'arrêt)
CONSTRAINTS = (
    (
        "uq_teacher_attendance_slot_date",
        "teacher_session_attendance",
        ("teacher_id", "slot_id", "date"),
        "pointages enseignant sur le même créneau le même jour",
    ),
    (
        "uq_attendance_context_day",
        "attendance_contexts",
        ("entity_type", "context_id", "date"),
        "appels de la même classe (ou du même examen) le même jour",
    ),
    (
        "uq_attendance_record_student",
        "attendance_records",
        ("context_id", "student_id"),
        "élèves présents deux fois dans le même appel",
    ),
)


def duplicate_groups(bind: sa.engine.Connection, table: str, columns: tuple[str, ...]) -> int:
    """Nombre de groupes qui violeraient la contrainte.

    Une ligne dont une colonne vaut NULL n'entre dans aucun groupe : MySQL ne
    la compare à rien, la contrainte non plus.
    """
    cols = ", ".join(columns)
    not_null = " AND ".join(f"{c} IS NOT NULL" for c in columns)
    query = sa.text(
        f"SELECT COUNT(*) FROM (SELECT {cols} FROM {table} WHERE {not_null} "
        f"GROUP BY {cols} HAVING COUNT(*) > 1) AS d"
    )
    return int(bind.execute(query).scalar() or 0)


def _has_unique(bind: sa.engine.Connection, table: str, name: str) -> bool:
    inspector = sa.inspect(bind)
    names = {u["name"] for u in inspector.get_unique_constraints(table)}
    names |= {i["name"] for i in inspector.get_indexes(table) if i.get("unique")}
    return name in names


def upgrade():
    bind = op.get_bind()
    pending = [c for c in CONSTRAINTS if not _has_unique(bind, c[1], c[0])]

    found = [
        f"{groups} groupe(s) de {label} (table {table})"
        for _, table, columns, label in pending
        if (groups := duplicate_groups(bind, table, columns))
    ]
    if found:
        raise RuntimeError(
            "Migration 0091 arrêtée, rien n'a été modifié. Doublons à résoudre avant : "
            + " ; ".join(found)
        )

    for name, table, columns, _ in pending:
        op.create_unique_constraint(name, table, list(columns))


def downgrade():
    bind = op.get_bind()
    for name, table, _, _ in CONSTRAINTS:
        if _has_unique(bind, table, name):
            op.drop_constraint(name, table, type_="unique")
