"""Configuration « qui encaisse par quel moyen », vue côté paramètres.

L'écran des permissions montre déjà ces droits, mais sous forme de slugs :
`payments:method:cash` n'apprend rien à une directrice. Ce service présente la
même matrice en clair — un profil, des moyens cochés — et écrit dans la même
table `role_permissions`. Il n'y a donc qu'une seule vérité, lisible de deux
façons, et non deux réglages qui peuvent se contredire.

Seuls les profils qui portent `payments:create` sont concernés : régler les
moyens de paiement d'un enseignant n'aurait aucun sens.
"""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.core.payment_methods import (
    DRAWER_METHODS,
    SELECTABLE_METHODS,
    method_label,
    method_permission,
)
from app.models.permission import RolePermission
from app.repositories import permission_repository as repo
from app.schemas.payment_method_settings import (
    PaymentMethodDescriptor,
    PaymentMethodRoleConfig,
    PaymentMethodSettingsResponse,
    PaymentMethodSettingsUpdate,
)

_CREATE_PERMISSION = "payments:create"


def _descriptors() -> list[PaymentMethodDescriptor]:
    return [
        PaymentMethodDescriptor(
            key=method,
            label=method_label(method),
            requires_cash_drawer=method in DRAWER_METHODS,
        )
        for method in SELECTABLE_METHODS
    ]


async def get_settings(db: AsyncSession) -> PaymentMethodSettingsResponse:
    """L'état actuel : les moyens existants, et ce que chaque profil peut saisir."""
    roles = await repo.list_roles_holding(db, _CREATE_PERMISSION)
    items: list[PaymentMethodRoleConfig] = []
    for role in roles:
        held = await repo.role_permission_slugs(db, role.id)
        items.append(
            PaymentMethodRoleConfig(
                role_id=role.id,
                role_name=role.name,
                role_label=role.description or role.name,
                allowed_methods=[
                    method for method in SELECTABLE_METHODS if method_permission(method) in held
                ],
            )
        )
    return PaymentMethodSettingsResponse(methods=_descriptors(), roles=items)


async def update_settings(
    db: AsyncSession, data: PaymentMethodSettingsUpdate, *, updated_by: int
) -> PaymentMethodSettingsResponse:
    """Applique la configuration, un profil à la fois.

    N'ajoute et ne retire que des slugs `payments:method:*` : le reste des
    droits du rôle n'est jamais touché, sans quoi cet écran deviendrait un
    moyen détourné de modifier des permissions qu'il ne montre pas.
    """
    encashing = {role.id: role for role in await repo.list_roles_holding(db, _CREATE_PERMISSION)}
    slug_ids = await repo.permission_ids_by_slug(
        db, [method_permission(method) for method in SELECTABLE_METHODS]
    )

    async with db.begin_nested():
        for entry in data.roles:
            role = encashing.get(entry.role_id)
            if role is None:
                raise NotFoundError("Role", entry.role_id)

            unknown = [m for m in entry.allowed_methods if m not in SELECTABLE_METHODS]
            if unknown:
                raise BusinessValidationError(
                    f"Moyen de paiement inconnu : {', '.join(sorted(unknown))}."
                )

            wanted = {
                slug_ids[method_permission(m)]
                for m in entry.allowed_methods
                if method_permission(m) in slug_ids
            }
            all_method_ids = set(slug_ids.values())

            await db.execute(
                delete(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id.in_(all_method_ids - wanted),
                )
            )
            existing = await repo.role_permission_slugs(db, role.id)
            for method in entry.allowed_methods:
                slug = method_permission(method)
                if slug in existing or slug not in slug_ids:
                    continue
                db.add(RolePermission(role_id=role.id, permission_id=slug_ids[slug]))

            await audit_log(
                db,
                entity_type="role",
                action=AuditAction.UPDATE,
                user_id=updated_by,
                entity_id=role.id,
                new_values={
                    "payment_methods": sorted(entry.allowed_methods),
                    "role_name": role.name,
                },
            )
        await db.flush()

    await db.commit()
    return await get_settings(db)
