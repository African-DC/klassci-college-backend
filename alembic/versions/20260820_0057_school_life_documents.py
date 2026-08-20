"""Actes de vie scolaire du college : registres, statuts de note, en-tete officiel.

Trois changements qui vont ensemble parce qu'ils servent les memes quatre
documents :

1. Le statut d'une note distingue enfin « pas encore saisie », « absent, zero
   d'office » et « rattrapage autorise ». Sans cette separation, un billet
   d'annulation de zero ne pourrait pas dire sur quoi il porte.
2. Deux registres : les convocations de tuteurs et les autorisations de
   rattrapage, avec les evaluations que chaque autorisation rouvre.
3. Les colonnes que l'en-tete officiel reclame : la DRENA de rattachement, une
   seconde ligne de devise, les armoiries, et un champ telephone assez large
   pour deux numeros. Cote eleve, l'etablissement d'origine et le numero de la
   decision de transfert, que la demande de dossier ne peut pas deviner.

Revision ID: 0055_school_life_documents
Revises: 0056_payment_survives_student
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0057_school_life_documents"
down_revision = "0056_payment_survives_student"
branch_labels = None
depends_on = None

# L'ordre des valeurs est celui du modele : MySQL stocke l'index, pas le texte.
_GRADE_STATUS_NEW = "ENUM('pending','entered','absent','retake_allowed')"
_GRADE_STATUS_OLD = "ENUM('pending','entered')"

_PERMISSIONS = (
    ("documents:school-file-request", "Issue a school file request"),
    ("documents:entry-slip", "Issue a class entry slip"),
    ("documents:parent-summons", "Summon a parent and keep the register"),
    ("documents:zero-cancellation", "Authorize a missed evaluation retake"),
)

# Qui signe quoi. `admin` et `director` portent tout le catalogue ; le
# secretariat edite les quatre actes au guichet ; l'educateur tient la vie
# scolaire ; le directeur des etudes correspond avec les autres etablissements.
_ROLE_GRANTS: dict[str, tuple[str, ...]] = {
    "admin": tuple(slug for slug, _ in _PERMISSIONS),
    "director": tuple(slug for slug, _ in _PERMISSIONS),
    "staff": tuple(slug for slug, _ in _PERMISSIONS),
    "educator": (
        "documents:entry-slip",
        "documents:parent-summons",
        "documents:zero-cancellation",
    ),
    "studies_director": ("documents:school-file-request",),
}


def _seed_permissions() -> None:
    values = ", ".join(f"('{slug}', '{name}')" for slug, name in _PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {values}")
    for role, slugs in _ROLE_GRANTS.items():
        in_list = ", ".join(f"'{slug}'" for slug in slugs)
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
            WHERE r.name = '{role}' AND p.slug IN ({in_list})
            """
        )


def upgrade() -> None:
    # --- 1. Statuts de note -------------------------------------------------
    op.execute(f"ALTER TABLE grades MODIFY COLUMN status {_GRADE_STATUS_NEW} NOT NULL")

    # --- 2. Registres de vie scolaire ---------------------------------------
    op.create_table(
        "parent_summons",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("parent_name", sa.String(200), nullable=True),
        sa.Column("academic_year_id", sa.BigInteger(), nullable=False),
        sa.Column("trimester", sa.Integer(), nullable=False),
        sa.Column("summons_date", sa.Date(), nullable=False),
        sa.Column("summons_time", sa.Time(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("issued_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("reference", sa.String(60), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum("pending", "attended", "missed", name="summons_outcome"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("outcome_notes", sa.Text(), nullable=True),
        sa.Column("outcome_recorded_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("outcome_recorded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("trimester >= 1 AND trimester <= 3", name="ck_parent_summons_trimester"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_id"], ["parents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["outcome_recorded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_parent_summons_student_id", "parent_summons", ["student_id"])
    op.create_index("idx_parent_summons_parent_id", "parent_summons", ["parent_id"])
    op.create_index("idx_parent_summons_year", "parent_summons", ["academic_year_id"])
    op.create_index("idx_parent_summons_trimester", "parent_summons", ["trimester"])
    op.create_index("idx_parent_summons_date", "parent_summons", ["summons_date"])
    op.create_index("idx_parent_summons_outcome", "parent_summons", ["outcome"])
    op.create_index("idx_parent_summons_issued_by", "parent_summons", ["issued_by_user_id"])
    op.create_index("idx_parent_summons_reference", "parent_summons", ["reference"])

    op.create_table(
        "retake_authorizations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("student_id", sa.BigInteger(), nullable=False),
        sa.Column("academic_year_id", sa.BigInteger(), nullable=False),
        sa.Column("trimester", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("issued_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("reference", sa.String(60), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "trimester >= 1 AND trimester <= 3", name="ck_retake_authorizations_trimester"
        ),
        sa.CheckConstraint(
            "period_end >= period_start", name="ck_retake_authorizations_period_order"
        ),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_retake_auth_student_id", "retake_authorizations", ["student_id"])
    op.create_index("idx_retake_auth_year", "retake_authorizations", ["academic_year_id"])
    op.create_index("idx_retake_auth_trimester", "retake_authorizations", ["trimester"])
    op.create_index("idx_retake_auth_issued_by", "retake_authorizations", ["issued_by_user_id"])
    op.create_index("idx_retake_auth_reference", "retake_authorizations", ["reference"])

    op.create_table(
        "retake_authorization_evaluations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("authorization_id", sa.BigInteger(), nullable=False),
        sa.Column("evaluation_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["authorization_id"], ["retake_authorizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["evaluation_id"], ["evaluations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "authorization_id", "evaluation_id", name="uq_retake_authorization_evaluation"
        ),
    )
    op.create_index(
        "idx_retake_auth_eval_authorization",
        "retake_authorization_evaluations",
        ["authorization_id"],
    )
    op.create_index(
        "idx_retake_auth_eval_evaluation",
        "retake_authorization_evaluations",
        ["evaluation_id"],
    )

    # --- 3. Identite de l'etablissement et origine de l'eleve ---------------
    op.alter_column(
        "school_settings",
        "phone",
        existing_type=sa.String(20),
        type_=sa.String(50),
        existing_nullable=True,
    )
    op.add_column("school_settings", sa.Column("drena_name", sa.String(150), nullable=True))
    op.add_column("school_settings", sa.Column("secondary_motto", sa.String(255), nullable=True))
    op.add_column("school_settings", sa.Column("coat_of_arms_url", sa.String(500), nullable=True))
    op.add_column("students", sa.Column("previous_school", sa.String(200), nullable=True))
    op.add_column("students", sa.Column("transfer_decision_number", sa.String(60), nullable=True))

    # --- 4. Permissions ------------------------------------------------------
    _seed_permissions()


def downgrade() -> None:
    slugs = ", ".join(f"'{slug}'" for slug, _ in _PERMISSIONS)
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE p.slug IN ({slugs})
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug IN ({slugs})")

    op.drop_column("students", "transfer_decision_number")
    op.drop_column("students", "previous_school")
    op.drop_column("school_settings", "coat_of_arms_url")
    op.drop_column("school_settings", "secondary_motto")
    op.drop_column("school_settings", "drena_name")
    op.alter_column(
        "school_settings",
        "phone",
        existing_type=sa.String(50),
        type_=sa.String(20),
        existing_nullable=True,
    )

    op.drop_table("retake_authorization_evaluations")
    op.drop_table("retake_authorizations")
    op.drop_table("parent_summons")

    # Les deux nouveaux statuts disparaissent : on ramene les notes concernees
    # a « pas encore saisie » plutot que de laisser MySQL les tronquer en
    # chaine vide. Un zero d'office redevient une case a remplir, ce qui est le
    # comportement d'avant cette migration.
    op.execute("UPDATE grades SET status = 'pending' WHERE status IN ('absent', 'retake_allowed')")
    op.execute(f"ALTER TABLE grades MODIFY COLUMN status {_GRADE_STATUS_OLD} NOT NULL")
