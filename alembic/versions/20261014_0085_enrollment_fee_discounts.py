"""Réductions individuelles des frais, sans altérer les versements.

Revision ID: 0085_fee_discounts
Revises: 0084_information_sheet
"""
import sqlalchemy as sa
from alembic import op

revision = "0085_fee_discounts"
down_revision = "0084_information_sheet"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("enrollment_fees", sa.Column("original_amount", sa.Numeric(15, 2), nullable=True))
    op.add_column("enrollment_fees", sa.Column("discount_kind", sa.String(12), nullable=True))
    op.add_column("enrollment_fees", sa.Column("discount_value", sa.Numeric(15, 2), nullable=True))
    op.add_column("enrollment_fees", sa.Column("discount_reason", sa.String(255), nullable=True))
    op.execute("INSERT IGNORE INTO permissions (slug, name) VALUES ('fees:discount:read', 'View student fee discounts'), ('fees:discount:manage', 'Manage student fee discounts')")
    op.execute("""
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.name IN ('admin', 'director')
        AND p.slug IN ('fees:discount:read', 'fees:discount:manage')
    """)

def downgrade() -> None:
    # Stop if any active discount exists: a downgrade must not silently restore old debts.
    count = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM enrollment_fees WHERE discount_kind IS NOT NULL"
    )).scalar_one()
    if count:
        raise RuntimeError("Active discounts exist. Reconcile them before downgrading 0085.")
    op.execute("""
        DELETE rp FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id
        WHERE p.slug IN ('fees:discount:read', 'fees:discount:manage')
    """)
    op.execute("DELETE FROM permissions WHERE slug IN ('fees:discount:read', 'fees:discount:manage')")
    for col in ("discount_reason", "discount_value", "discount_kind", "original_amount"):
        op.drop_column("enrollment_fees", col)
