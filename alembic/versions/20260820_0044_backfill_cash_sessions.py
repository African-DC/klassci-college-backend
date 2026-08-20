"""Crée les sessions de caisse manquantes pour les versements antérieurs.

Avant la 0043, les versements n'avaient pas de journée de caisse. Le service
compensait avec une branche « session inexistante » qui fabriquait une réponse
synthétique portant `id: 0` — un sentinelle qui ment au contrat, et une
fonction de dépôt entière dédiée à retrouver ces caissiers fantômes.

Créer les lignes manquantes supprime le cas au lieu de le gérer. Les journées
reconstituées sont marquées `open` : personne n'a compté ces tiroirs, donc on
ne peut pas inventer un montant compté ni un écart. C'est exactement ce que la
branche synthétique affichait, sans le code.

La 0043 est déjà déployée : ce rattrapage doit donc être une migration à part.

Revision ID: 0044_backfill_cash_sessions
Revises: 0043_cash_sessions
Create Date: 2026-08-20
"""

from alembic import op

revision = "0044_backfill_cash_sessions"
down_revision = "0043_cash_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `INSERT IGNORE` s'appuie sur uq_cash_session_cashier_date : les journées
    # déjà ouvertes par la 0043 ne sont pas dupliquées, et rejouer la migration
    # ne fait rien.
    op.execute(
        """
        INSERT IGNORE INTO cash_sessions
            (cashier_user_id, business_date, status, opened_at, created_at, updated_at)
        SELECT
            p.received_by,
            DATE(p.created_at),
            'open',
            MIN(p.created_at),
            NOW(),
            NOW()
        FROM payments p
        WHERE p.received_by IS NOT NULL
          AND p.status IN ('completed', 'pending')
        GROUP BY p.received_by, DATE(p.created_at)
        """
    )


def downgrade() -> None:
    # On ne supprime rien : distinguer une journée reconstituée d'une journée
    # réellement ouverte demanderait un marqueur, et supprimer trop large
    # effacerait des clôtures signées depuis.
    pass
