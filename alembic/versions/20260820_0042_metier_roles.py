"""Roles metier : caissier, educateur, directeur des etudes.

- Cree les roles `cashier`, `educator`, `studies_director` et leur matrice de
  permissions sur les tenants existants.
- Corrige le comptable : il lui manquait `admin:academic-years:read`, ce qui
  faisait repondre 403 a tous les ecrans filtrant par annee scolaire (dont la
  page Frais). Il recupere aussi la configuration complete de la grille
  tarifaire, qui est son metier.
- Complete le secretariat (slug historique `staff`, dont seul le libelle change)
  avec les parents, le referentiel et les documents officiels.
- Rattrape `performance:read`, seedee par la migration 0034 mais absente de
  `app/services/tenants/permissions.py` : les tenants provisionnes depuis ce
  module ne l'avaient jamais eue.

Aucune permission n'est retiree ici. La bascule des comptes d'un role a un
autre (ex : les caissieres de ROSTAN encore en `accountant`) est une operation
de donnees, volontairement hors migration.

Revision ID: 0042_metier_roles
Revises: 0041_harden_document_seals
Create Date: 2026-08-20
"""

from alembic import op

revision = "0042_metier_roles"
down_revision = "0041_harden_document_seals"
branch_labels = None
depends_on = None


_NEW_PERMISSIONS = [
    ("performance:read", "View teacher and staff performance"),
]

_NEW_ROLES = [
    ("cashier", "Caissier / Caissière"),
    ("educator", "Éducateur"),
    ("studies_director", "Directeur des études"),
]

# Libelle seul : le slug `staff` reste inchange (porte par des comptes en
# production, present dans le JWT et dans l'historique d'audit).
_ROLE_DESCRIPTION_UPDATES = {
    "staff": "Secrétariat",
}

_REFERENTIEL_READ = [
    "admin:academic-years:read",
    "admin:levels:read",
    "admin:series:read",
    "admin:classes:read",
]

_FEE_CONFIG = [
    "admin:fee-categories:read",
    "admin:fee-categories:create",
    "admin:fee-categories:update",
    "admin:fee-categories:delete",
    "admin:fee-variants:read",
    "admin:fee-variants:create",
    "admin:fee-variants:update",
    "admin:fee-variants:delete",
    "admin:fee-options:read",
    "admin:fee-options:create",
    "admin:fee-options:update",
    "admin:fee-options:delete",
]

_ROLE_PERMISSION_MATRIX: dict[str, list[str]] = {
    "admin": ["performance:read"],
    "director": ["performance:read"],
    "staff": [
        *_REFERENTIEL_READ,
        "admin:parents:read",
        "admin:parents:create",
        "admin:parents:update",
        "documents:certificate",
        "documents:attendance",
    ],
    "accountant": [
        *_REFERENTIEL_READ,
        *_FEE_CONFIG,
        "admin:students:read",
        "reports:generate",
        "leave:request",
    ],
    "cashier": [
        "payments:read",
        "payments:create",
        "enrollments:read",
        "admin:students:read",
        *_REFERENTIEL_READ,
        "leave:request",
    ],
    "educator": [
        "enrollments:read",
        "enrollments:create",
        "enrollments:update",
        "admin:students:read",
        "admin:students:create",
        "admin:students:update",
        "admin:parents:read",
        "admin:parents:create",
        "admin:parents:update",
        *_REFERENTIEL_READ,
        "payments:read",
        "attendance:read",
        "reports:read",
        "documents:certificate",
        "documents:attendance",
        "leave:request",
    ],
    "studies_director": [
        *_REFERENTIEL_READ,
        "admin:classes:create",
        "admin:classes:update",
        "admin:series:write",
        "admin:rooms:read",
        "admin:rooms:create",
        "admin:rooms:update",
        "admin:subjects:read",
        "admin:subjects:create",
        "admin:subjects:update",
        "admin:subjects:delete",
        "admin:teachers:read",
        "admin:teachers:update",
        "admin:teachers:attendance",
        "admin:teachers:attendance:read",
        "admin:students:read",
        "enrollments:read",
        "timetable:read",
        "timetable:write",
        "timetable:generate",
        "grades:read",
        "grades:write",
        "grades:edit",
        "bulletins:generate",
        "attendance:read",
        "attendance:create",
        "attendance:update",
        "reports:read",
        "reports:generate",
        "reports:override",
        "performance:read",
        "documents:certificate",
        "documents:attendance",
        "leave:request",
        "leave:approve",
    ],
}


# Permissions REELLEMENT ajoutees par cette migration aux roles preexistants.
# Distinct de la matrice ci-dessus, qui est idempotente et peut re-accorder ce
# que le role possedait deja : `staff` avait `admin:classes:read` avant 0042,
# le revoquer au downgrade serait une regression.
_DOWNGRADE_REVOKE: dict[str, list[str]] = {
    "staff": [
        "admin:academic-years:read",
        "admin:levels:read",
        "admin:series:read",
        "admin:parents:read",
        "admin:parents:create",
        "admin:parents:update",
        "documents:certificate",
        "documents:attendance",
    ],
    "accountant": [
        *_REFERENTIEL_READ,
        *_FEE_CONFIG,
        "admin:students:read",
        "reports:generate",
        "leave:request",
    ],
}


def _quote(value: str) -> str:
    """Echappe une valeur SQL litterale (apostrophes des libelles francais)."""
    return value.replace("'", "''")


def upgrade() -> None:
    values_sql = ", ".join(f"('{_quote(s)}', '{_quote(n)}')" for s, n in _NEW_PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {values_sql}")

    for name, description in _NEW_ROLES:
        op.execute(
            "INSERT IGNORE INTO roles (name, description, created_at, updated_at) "
            f"VALUES ('{_quote(name)}', '{_quote(description)}', NOW(), NOW())"
        )

    for name, description in _ROLE_DESCRIPTION_UPDATES.items():
        op.execute(
            f"UPDATE roles SET description = '{_quote(description)}' WHERE name = '{_quote(name)}'"
        )

    for role_name, slugs in _ROLE_PERMISSION_MATRIX.items():
        slugs_sql = ", ".join(f"'{_quote(slug)}'" for slug in sorted(set(slugs)))
        op.execute(
            f"""
            INSERT IGNORE INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.name = '{_quote(role_name)}'
            AND p.slug IN ({slugs_sql})
            """
        )


def downgrade() -> None:
    # Les roles metier disparaissent : on retire d'abord les rattachements pour
    # ne pas buter sur les cles etrangeres. Les comptes concernes se retrouvent
    # sans role — c'est la consequence assumee d'un downgrade de creation de role.
    new_role_names = ", ".join(f"'{_quote(name)}'" for name, _ in _NEW_ROLES)
    op.execute(
        f"DELETE ur FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
        f"WHERE r.name IN ({new_role_names})"
    )
    op.execute(
        f"DELETE rp FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
        f"WHERE r.name IN ({new_role_names})"
    )
    op.execute(f"DELETE FROM roles WHERE name IN ({new_role_names})")

    op.execute("UPDATE roles SET description = 'Personnel administratif' WHERE name = 'staff'")

    # Les permissions ajoutees aux roles preexistants sont retirees une a une.
    # `performance:read` n'est pas supprimee du catalogue : la migration 0034 la
    # seede aussi et la retirer ici casserait un downgrade partiel.
    for role_name, revoked in _DOWNGRADE_REVOKE.items():
        slugs_sql = ", ".join(f"'{_quote(slug)}'" for slug in sorted(set(revoked)))
        op.execute(
            f"""
            DELETE rp FROM role_permissions rp
            JOIN roles r ON r.id = rp.role_id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE r.name = '{_quote(role_name)}'
            AND p.slug IN ({slugs_sql})
            """
        )
