"""Les quatre trous du rapport de fin de trimestre de la DEEP.

Le canevas officiel réclame 27 tableaux. KLASSCI savait déjà répondre à la
plupart, mais quatre portaient sur des informations qu'aucune table ne
conservait : les visites de classe, les formations d'enseignants, les
transferts et réintégrations, et les bourses. S'y ajoutent deux numéros
administratifs — CNPS et autorisation d'enseigner — que l'inspection lit
ligne à ligne sur la situation du personnel.

## Rétro-compatibilité

Tout est ajouté, rien n'est modifié : quatre tables neuves et quatre colonnes
facultatives. Aucune ligne existante ne change de sens, et un établissement
qui ne saisit rien verra simplement ces tableaux marqués « à compléter » —
jamais remplis de zéros, qui se liraient comme un constat.

Revision ID: 0057_deep_trimester_report_data
Revises: 0056_payment_survives_student
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0057_deep_trimester_report_data"
down_revision = "0056_payment_survives_student"
branch_labels = None
depends_on = None

_SCHOLARSHIP_KIND = sa.Enum("bourse_entiere", "demi_bourse", name="scholarship_kind")
_TRANSFER_KIND = sa.Enum("transfert", "reintegration", name="transfer_kind")


def upgrade() -> None:
    # --- Colonnes administratives sur le personnel -------------------------
    for table in ("teacher_profiles", "staff_profiles"):
        op.add_column(table, sa.Column("cnps_number", sa.String(50), nullable=True))
        op.add_column(
            table,
            sa.Column("teaching_authorization_number", sa.String(50), nullable=True),
        )

    # --- Visites de classe (tableau 1) ------------------------------------
    op.create_table(
        "class_visits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("teacher_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("class_id", sa.BigInteger(), nullable=True),
        sa.Column("academic_year_id", sa.BigInteger(), nullable=False),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("visitor_name", sa.String(200), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["teacher_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_class_visits_teacher", "class_visits", ["teacher_id"])
    op.create_index("idx_class_visits_year", "class_visits", ["academic_year_id"])
    op.create_index("idx_class_visits_date", "class_visits", ["visit_date"])

    # --- Formations (tableau 2) -------------------------------------------
    op.create_table(
        "teacher_trainings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("teacher_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("academic_year_id", sa.BigInteger(), nullable=False),
        sa.Column("discipline_label", sa.String(150), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("training_date", sa.Date(), nullable=False),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["teacher_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_teacher_trainings_teacher", "teacher_trainings", ["teacher_id"])
    op.create_index("idx_teacher_trainings_year", "teacher_trainings", ["academic_year_id"])
    op.create_index("idx_teacher_trainings_date", "teacher_trainings", ["training_date"])

    # --- Transferts et réintégrations (tableau 9) -------------------------
    op.create_table(
        "student_transfers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("enrollment_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", _TRANSFER_KIND, nullable=False),
        sa.Column("origin_school", sa.String(200), nullable=True),
        sa.Column("decision_number", sa.String(50), nullable=True),
        sa.Column("transfer_date", sa.Date(), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_student_transfers_enrollment", "student_transfers", ["enrollment_id"])
    op.create_index("idx_student_transfers_kind", "student_transfers", ["kind"])

    # --- Bourses (tableau 13) ---------------------------------------------
    op.create_table(
        "scholarships",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("enrollment_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", _SCHOLARSHIP_KIND, nullable=False),
        sa.Column("provider", sa.String(200), nullable=True),
        sa.Column("decision_number", sa.String(50), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("granted_on", sa.Date(), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["enrollment_id"], ["enrollments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_scholarships_enrollment", "scholarships", ["enrollment_id"])
    op.create_index("idx_scholarships_kind", "scholarships", ["kind"])


def downgrade() -> None:
    # On supprime les tables sans passer par `drop_index` : sous MySQL, un index
    # posé sur une colonne de clé étrangère est adopté par la contrainte, et le
    # retirer d'abord échoue avec « needed in a foreign key constraint ». La
    # suppression de la table emporte de toute façon ses index.
    op.drop_table("scholarships")
    op.drop_table("student_transfers")
    op.drop_table("teacher_trainings")
    op.drop_table("class_visits")

    for table in ("staff_profiles", "teacher_profiles"):
        op.drop_column(table, "teaching_authorization_number")
        op.drop_column(table, "cnps_number")

    # Les types ENUM MySQL sont portés par la colonne : la suppression des
    # tables suffit, rien à nettoyer côté catalogue.
    _SCHOLARSHIP_KIND.drop(op.get_bind(), checkfirst=True)
    _TRANSFER_KIND.drop(op.get_bind(), checkfirst=True)
