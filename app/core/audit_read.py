"""Traçage des consultations de dossiers sensibles.

Savoir qui a créé, modifié ou supprimé ne suffit pas : dans un établissement,
consulter le dossier d'un élève, un versement ou un bulletin est déjà un acte
qui engage. Le reste — une liste de classes, un emploi du temps — n'a pas à
peupler le journal : tracer tout revient à ne rien tracer, parce que plus
personne ne relit.

La consultation est déclarée comme une dépendance, à côté de la permission,
plutôt qu'écrite dans le corps de chaque endpoint. Les routeurs ne gagnent
pas une ligne de logique, et il reste un seul endroit où la règle change.
"""

from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.dependencies import TokenData, get_current_user, get_tenant_db


def audit_read(entity_type: str, *, param: str) -> Any:
    """Enregistre l'accès au dossier `param` comme une consultation.

    Journalise l'accès **autorisé** : la dépendance de permission tourne en
    parallèle, un utilisateur sans droit n'arrive jamais ici. Un identifiant
    inexistant laisse une trace lui aussi, et c'est voulu — quelqu'un qui
    balaie des numéros de dossier est exactement ce qu'un journal doit montrer.
    """

    async def _record(
        request: Request,
        current_user: TokenData = Depends(get_current_user),
        db: AsyncSession = Depends(get_tenant_db),
    ) -> None:
        raw = request.path_params.get(param)
        try:
            entity_id = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            entity_id = None

        await audit_log(
            db,
            entity_type=entity_type,
            action=AuditAction.READ,
            user_id=current_user.user_id,
            entity_id=entity_id,
            ip_address=request.client.host if request.client else None,
        )
        # Une lecture ne commite rien d'autre : sans ce commit, la trace
        # disparaitrait avec la session.
        await db.commit()

    return Depends(_record)
