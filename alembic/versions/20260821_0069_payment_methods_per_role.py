"""Quatre opérateurs mobile money distincts, et un droit d'encaisser par moyen.

Deux changements liés.

**Les moyens de paiement.** `mobile_money` couvrait à lui seul les quatre
opérateurs du marché ivoirien. La caisse les rapproche séparément, ils
deviennent donc quatre valeurs : `wave`, `mtn_momo`, `orange_money`,
`moov_money`. `mobile_money` est CONSERVÉ en base. Les versements déjà
enregistrés sous cette valeur ne sont pas réécrits : personne ne peut savoir
après coup lequel était Wave et lequel était Moov Money, une réécriture
produirait un livre de caisse faux, et un reçu déjà remis à une famille
cesserait de correspondre au papier qu'elle détient. La valeur reste lisible et
comptée, simplement plus saisissable — ce que la couche applicative fait
respecter, pas la base.

**Le droit d'encaisser par moyen.** Un slug par moyen saisissable. Ils sont
accordés à TOUS les rôles qui portent déjà `payments:create`, ce qui reproduit
exactement le comportement d'avant : qui pouvait encaisser pouvait encaisser
par n'importe quel moyen. Aucune école en service ne voit son guichet changer
tant qu'elle n'a pas ouvert l'écran de configuration.

Revision ID: 0069_payment_methods
Revises: 0068_student_birth_place
Create Date: 2026-08-21
"""

from alembic import op

revision = "0069_payment_methods"
down_revision = "0068_student_birth_place"
branch_labels = None
depends_on = None


# Ordre de l'ENUM MySQL. Il suit la fréquence réelle au guichet, comme
# `app.core.payment_methods.DISPLAY_ORDER`, et `mobile_money` ferme la marche
# en tant que valeur historique.
_METHODS_AFTER = (
    "cash",
    "wave",
    "mtn_momo",
    "orange_money",
    "moov_money",
    "bank_transfer",
    "cheque",
    "mobile_money",
)
_METHODS_BEFORE = ("cash", "mobile_money", "bank_transfer", "cheque")

_NEW_OPERATORS = ("wave", "mtn_momo", "orange_money", "moov_money")

_SELECTABLE = (
    "cash",
    "wave",
    "mtn_momo",
    "orange_money",
    "moov_money",
    "bank_transfer",
    "cheque",
)

_NEW_PERMISSIONS = [(f"payments:method:{m}", f"Take payment by {m}") for m in _SELECTABLE]


def _enum_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE payments MODIFY COLUMN method "
        f"ENUM({_enum_sql(_METHODS_AFTER)}) NOT NULL"
    )

    values_sql = ", ".join(f"('{slug}', '{name}')" for slug, name in _NEW_PERMISSIONS)
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES {values_sql}")

    # Tout rôle qui peut déjà encaisser reçoit les sept moyens : c'est le
    # comportement actuel, écrit noir sur blanc plutôt que sous-entendu.
    slugs_sql = ", ".join(f"'{slug}'" for slug, _ in _NEW_PERMISSIONS)
    op.execute(
        f"""
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE p.slug IN ({slugs_sql})
        AND EXISTS (
            SELECT 1 FROM role_permissions rp
            JOIN permissions pc ON pc.id = rp.permission_id
            WHERE rp.role_id = r.id AND pc.slug = 'payments:create'
        )
        """
    )


def downgrade() -> None:
    slugs_sql = ", ".join(f"'{slug}'" for slug, _ in _NEW_PERMISSIONS)
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.slug IN ({slugs_sql})
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug IN ({slugs_sql})")

    # Revenir en arrière impose de vider les quatre valeurs qui n'existeront
    # plus. Les replier sur `mobile_money` est l'inverse exact de la scission :
    # c'est la catégorie dont ces opérateurs ont été extraits, et la seule
    # valeur qui reste vraie après coup. L'information de l'opérateur est
    # perdue — c'est le prix d'un retour arrière, et la raison pour laquelle
    # on n'en fait pas un aller-retour de routine.
    operators_sql = ", ".join(f"'{m}'" for m in _NEW_OPERATORS)
    op.execute(f"UPDATE payments SET method = 'mobile_money' WHERE method IN ({operators_sql})")
    op.execute(
        f"ALTER TABLE payments MODIFY COLUMN method "
        f"ENUM({_enum_sql(_METHODS_BEFORE)}) NOT NULL"
    )
