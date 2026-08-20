"""Journal d'audit : identite figee, consultations, index de lecture.

Trois changements sur `audit_logs` :

1. `actor_email` / `actor_role` — l'identite de l'auteur figee a l'ecriture.
   Un compte supprime ou reattribue ne doit pas effacer la trace de ce qu'il
   a fait ; `user_id` seul devient un numero orphelin. Le nom affichable
   reste resolu a la lecture depuis les fiches : on veut retrouver la
   personne telle qu'elle s'appelle aujourd'hui.

2. La valeur `read` dans l'ENUM `action` — consulter un dossier d'eleve, un
   versement ou un bulletin est deja un acte qui engage.

3. Des index. Sans eux, la page journal fait un balayage complet d'une table
   qui grossit a chaque geste de la journee, et devient inutilisable au
   moment precis ou on en a besoin.

Le backfill remplit `actor_email` / `actor_role` depuis `users` pour
l'historique deja ecrit. Les lignes dont l'auteur n'existe plus restent
vides : inventer une identite serait pire que d'admettre qu'on ne l'a pas.

Revision ID: 0048_audit_journal
Revises: 0047_document_release_override
Create Date: 2026-08-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0048_audit_journal"
down_revision = "0047_document_release_override"
branch_labels = None
depends_on = None

_ACTIONS_WITH_READ = "'create','update','delete','login','logout','read'"
_ACTIONS_WITHOUT_READ = "'create','update','delete','login','logout'"


def _has_column(bind: object, name: str) -> bool:
    return bool(
        bind.execute(  # type: ignore[attr-defined]
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'audit_logs' "
                "AND column_name = :name"
            ),
            {"name": name},
        ).scalar()
    )


def _has_index(bind: object, name: str) -> bool:
    return bool(
        bind.execute(  # type: ignore[attr-defined]
            sa.text(
                "SELECT 1 FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'audit_logs' "
                "AND index_name = :name LIMIT 1"
            ),
            {"name": name},
        ).scalar()
    )


def upgrade() -> None:
    # Certains index existent deja sur les etablissements ouverts tot, et une
    # execution interrompue peut avoir pose les colonnes sans enregistrer la
    # revision. On verifie plutot que de supposer : une migration qui echoue a
    # mi-chemin bloque toutes les suivantes pour ce tenant.
    bind = op.get_bind()

    if not _has_column(bind, "actor_email"):
        op.add_column("audit_logs", sa.Column("actor_email", sa.String(255), nullable=True))
    if not _has_column(bind, "actor_role"):
        op.add_column("audit_logs", sa.Column("actor_role", sa.String(50), nullable=True))

    op.execute(f"ALTER TABLE audit_logs MODIFY COLUMN action ENUM({_ACTIONS_WITH_READ}) NOT NULL")

    op.execute(
        """
        UPDATE audit_logs a
        JOIN users u ON u.id = a.user_id
        SET a.actor_email = u.email, a.actor_role = u.role
        WHERE a.actor_email IS NULL
        """
    )

    # La page journal filtre par date (tri par defaut), par entite, par auteur
    # et par action. Un index par axe de filtre reellement propose.
    for index_name, columns in (
        ("idx_audit_logs_created_at", ["created_at"]),
        ("idx_audit_logs_entity", ["entity_type", "entity_id"]),
        ("idx_audit_logs_user_id", ["user_id"]),
        ("idx_audit_logs_action", ["action"]),
    ):
        if not _has_index(bind, index_name):
            op.create_index(index_name, "audit_logs", columns)

    # Droits de lecture du journal. `audit:read` ouvre tout (direction),
    # `audit:read:financial` n'ouvre que les ecritures d'argent (comptable).
    op.execute(
        """
        INSERT IGNORE INTO permissions (slug, name) VALUES
        ('audit:read', 'Read the full audit journal'),
        ('audit:read:financial', 'Read the financial audit journal')
        """
    )
    for role_name, slugs in (
        ("admin", ("audit:read", "audit:read:financial")),
        ("director", ("audit:read", "audit:read:financial")),
        ("accountant", ("audit:read:financial",)),
    ):
        slugs_sql = ", ".join(f"'{slug}'" for slug in slugs)
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name = '{role_name}'
            AND p.slug IN ({slugs_sql})
            """
        )


def downgrade() -> None:
    op.execute(
        """
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.slug IN ('audit:read', 'audit:read:financial')
        """
    )
    op.execute("DELETE FROM permissions WHERE slug IN ('audit:read', 'audit:read:financial')")

    bind = op.get_bind()
    for index_name in (
        "idx_audit_logs_action",
        "idx_audit_logs_user_id",
        "idx_audit_logs_entity",
        "idx_audit_logs_created_at",
    ):
        if _has_index(bind, index_name):
            op.drop_index(index_name, table_name="audit_logs")

    # Les consultations n'ont pas d'equivalent dans l'ancien ENUM : on les
    # supprime plutot que de les travestir en une autre action.
    op.execute("DELETE FROM audit_logs WHERE action = 'read'")
    op.execute(
        f"ALTER TABLE audit_logs MODIFY COLUMN action ENUM({_ACTIONS_WITHOUT_READ}) NOT NULL"
    )

    for column_name in ("actor_role", "actor_email"):
        if _has_column(bind, column_name):
            op.drop_column("audit_logs", column_name)
