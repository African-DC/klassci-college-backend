"""Payment allocations + FeeCategory.priority + Payment.enrollment_id.

Refactor metier majeur : un paiement cible une INSCRIPTION (acte caissier),
le systeme alloue automatiquement aux frais impayes par ordre de priorite.

Schema cible :
- fee_categories.priority SMALLINT (lower = paid first, default 100)
- payments.enrollment_id BigInteger (acte caissier, NOT NULL post-backfill)
- payments.enrollment_fee_id devient nullable (deprecated, conserve 1 release)
- payment_allocations (payment_id, enrollment_fee_id, amount) — N splits / payment

Backfill :
- fee_categories.priority : 10 Inscription / 20 T1 / 30 T2 / 40 T3 / 50 COGES /
  60 Tenue / 100 reste (matching par name LIKE)
- payments.enrollment_id : derive via enrollment_fees.enrollment_id
- payment_allocations : 1 row par Payment existant (amount = payment.amount)

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------
    # 1. fee_categories.priority — SMALLINT, default 100
    # ---------------------------------------------------------------
    op.add_column(
        "fee_categories",
        sa.Column(
            "priority",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("100"),
        ),
    )

    # Backfill priorities matching ivorian school conventions
    op.execute(
        """
        UPDATE fee_categories SET priority = 10
        WHERE LOWER(name) LIKE '%inscription%'
        """
    )
    op.execute(
        """
        UPDATE fee_categories SET priority = 20
        WHERE LOWER(name) LIKE '%t1%'
           OR LOWER(name) LIKE '%trimestre 1%'
           OR LOWER(name) LIKE '%scolarite t1%'
        """
    )
    op.execute(
        """
        UPDATE fee_categories SET priority = 30
        WHERE LOWER(name) LIKE '%t2%'
           OR LOWER(name) LIKE '%trimestre 2%'
           OR LOWER(name) LIKE '%scolarite t2%'
        """
    )
    op.execute(
        """
        UPDATE fee_categories SET priority = 40
        WHERE LOWER(name) LIKE '%t3%'
           OR LOWER(name) LIKE '%trimestre 3%'
           OR LOWER(name) LIKE '%scolarite t3%'
        """
    )
    op.execute(
        """
        UPDATE fee_categories SET priority = 50
        WHERE LOWER(name) LIKE '%coges%'
        """
    )
    op.execute(
        """
        UPDATE fee_categories SET priority = 60
        WHERE LOWER(name) LIKE '%tenue%'
           OR LOWER(name) LIKE '%uniforme%'
        """
    )

    # ---------------------------------------------------------------
    # 2. payments.enrollment_id — nullable temporairement pour backfill
    # ---------------------------------------------------------------
    op.add_column(
        "payments",
        sa.Column("enrollment_id", sa.BigInteger(), nullable=True),
    )

    # Backfill : derive enrollment_id depuis enrollment_fees
    op.execute(
        """
        UPDATE payments p
        JOIN enrollment_fees ef ON p.enrollment_fee_id = ef.id
        SET p.enrollment_id = ef.enrollment_id
        """
    )

    # Maintenant NOT NULL + FK + index
    op.alter_column(
        "payments",
        "enrollment_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_payments_enrollment",
        "payments",
        "enrollments",
        ["enrollment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("idx_payments_enrollment", "payments", ["enrollment_id"])

    # ---------------------------------------------------------------
    # 3. payments.enrollment_fee_id devient nullable (deprecated)
    #    On garde la colonne 1 release pour rollback rapide.
    # ---------------------------------------------------------------
    op.alter_column(
        "payments",
        "enrollment_fee_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )

    # ---------------------------------------------------------------
    # 4. payment_allocations — table de splits
    # ---------------------------------------------------------------
    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("payment_id", sa.BigInteger(), nullable=False),
        sa.Column("enrollment_fee_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["enrollment_fee_id"],
            ["enrollment_fees.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_payment_allocations_payment",
        "payment_allocations",
        ["payment_id"],
    )
    op.create_index(
        "idx_payment_allocations_fee",
        "payment_allocations",
        ["enrollment_fee_id"],
    )

    # ---------------------------------------------------------------
    # 5. Backfill payment_allocations : 1 row par Payment existant
    #    amount = payment.amount entiere (allocation directe au fee
    #    historique). Conserve l'historique comptable.
    # ---------------------------------------------------------------
    op.execute(
        """
        INSERT INTO payment_allocations
            (payment_id, enrollment_fee_id, amount, created_at, updated_at)
        SELECT id, enrollment_fee_id, amount, created_at, updated_at
        FROM payments
        WHERE enrollment_fee_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("payment_allocations")

    # Order matters on MySQL: drop FK BEFORE its supporting index, otherwise
    # 1553 "Cannot drop index: needed in a foreign key constraint".
    op.drop_constraint("fk_payments_enrollment", "payments", type_="foreignkey")
    op.drop_index("idx_payments_enrollment", table_name="payments")
    op.drop_column("payments", "enrollment_id")

    # Restore enrollment_fee_id NOT NULL (les rows existantes l'ont toujours)
    op.alter_column(
        "payments",
        "enrollment_fee_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )

    op.drop_column("fee_categories", "priority")
