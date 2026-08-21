"""Qui peut encaisser par quel moyen, et ce qu'on répond quand ce n'est pas le cas.

Deux filtres se composent, dans cet ordre :

1. **L'établissement** — `school_settings.enabled_payment_methods`. Ce que
   l'école accepte, tous guichets confondus. `NULL` signifie « tous », ce qui
   préserve les établissements déjà en service.
2. **Le rôle** — les permissions `payments:method:*`. Qui, parmi ceux qui
   peuvent encaisser, peut encaisser par ce moyen-là.

Le second filtre existe parce que le comptable du collège Rostan encaisse en
Wave, MTN MoMo, Orange Money, Moov Money, virement et chèque, mais jamais en
espèces. Les espèces engagent un tiroir physique, donc une journée de caisse
ouverte et un comptage le soir ; les autres moyens laissent une trace bancaire
ou opérateur et n'ont rien à compter. Autoriser quelqu'un à saisir des espèces,
c'est lui ouvrir un tiroir.

La résolution passe par la matrice rôle/permission, jamais par le nom d'un
rôle : `if role == "accountant"` serait une permission en dur.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData
from app.core.exceptions import PaymentMethodNotAllowedError
from app.core.payment_methods import (
    HISTORICAL_METHODS,
    SELECTABLE_METHODS,
    method_label,
    method_permission,
)


def _human_list(labels: list[str]) -> str:
    """« Wave, MTN MoMo et Orange Money » — pas « Wave, MTN MoMo, Orange Money »."""
    if not labels:
        return "aucun"
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} et {labels[-1]}"


async def school_accepted_methods(db: AsyncSession) -> set[str] | None:
    """Ce que l'établissement accepte, ou `None` s'il n'a rien configuré.

    `None` n'est pas « rien » mais « tous » : la colonne est vide sur toute
    école qui n'a jamais ouvert cet écran, et leur bloquer la caisse pour une
    option jamais remplie serait une régression pure.
    """
    from app.models.academic import SchoolSettings

    stmt = select(SchoolSettings.enabled_payment_methods).limit(1)
    configured = (await db.execute(stmt)).scalar_one_or_none()
    if not configured:
        return None
    accepted = {key.strip() for key in configured.split(",") if key.strip()}
    return accepted or None


async def granted_methods(db: AsyncSession, actor: TokenData) -> set[str]:
    """Les moyens que le rôle de l'appelant autorise.

    Une seule lecture de la matrice pour les sept slugs, plutôt qu'une par
    moyen : c'est le chemin d'un encaissement au guichet.
    """
    if actor.auth_method == "pat":
        from app.services.pat_service import scope_matches

        return {
            method
            for method in SELECTABLE_METHODS
            if scope_matches(actor.pat_scopes, method_permission(method))
        }

    from app.repositories.permission_repository import list_user_permissions

    held = set(await list_user_permissions(db, actor.user_id))
    return {method for method in SELECTABLE_METHODS if method_permission(method) in held}


async def allowed_methods_for(db: AsyncSession, actor: TokenData) -> list[str]:
    """Ce que cet appelant peut réellement saisir, dans l'ordre d'affichage.

    C'est cette liste que le formulaire d'encaissement propose : un moyen que
    la personne ne peut pas utiliser n'a rien à faire dans le sélecteur, et le
    lui faire choisir avant de le refuser à l'enregistrement serait lui faire
    perdre une saisie devant la famille.
    """
    accepted = await school_accepted_methods(db)
    granted = await granted_methods(db, actor)
    return [
        method
        for method in SELECTABLE_METHODS
        if method in granted and (accepted is None or method in accepted)
    ]


async def ensure_method_allowed(db: AsyncSession, actor: TokenData, method: str) -> None:
    """Laisse passer, ou refuse en disant quoi faire ensuite.

    L'ordre des contrôles va du plus général au plus personnel : une valeur qui
    n'existe pas, puis une école qui n'accepte pas ce moyen, puis une personne
    qui n'y a pas droit. Inverser reviendrait à répondre « voyez la caisse » à
    quelqu'un dont l'école n'accepte pas du tout ce moyen.
    """
    if method in HISTORICAL_METHODS:
        raise PaymentMethodNotAllowedError(
            f"« {method_label(method)} » est une valeur historique : elle reste "
            f"lisible sur les anciens versements mais ne peut plus être saisie. "
            f"Choisissez l'opérateur réellement utilisé."
        )

    if method not in SELECTABLE_METHODS:
        raise PaymentMethodNotAllowedError(f"Moyen de paiement inconnu : « {method} ».")

    accepted = await school_accepted_methods(db)
    if accepted is not None and method not in accepted:
        raise PaymentMethodNotAllowedError(
            f"L'établissement n'accepte pas les versements par "
            f"{method_label(method)}. Moyens acceptés : "
            f"{_human_list([method_label(m) for m in SELECTABLE_METHODS if m in accepted])}."
        )

    granted = await granted_methods(db, actor)
    if method in granted:
        return

    mine = [
        method_label(m)
        for m in SELECTABLE_METHODS
        if m in granted and (accepted is None or m in accepted)
    ]

    from app.repositories.permission_repository import list_roles_with_permission

    holders = await list_roles_with_permission(db, method_permission(method))

    message = (
        f"Vous n'êtes pas autorisé à encaisser par {method_label(method)}. "
        f"Vos moyens : {_human_list(mine)}."
    )
    if holders:
        message += f" Pour un versement par {method_label(method)}, adressez-vous à : {_human_list(holders)}."
    else:
        message += (
            f" Aucun profil n'est actuellement autorisé à encaisser par "
            f"{method_label(method)} : la direction peut l'activer dans "
            f"Paramètres → Moyens de paiement."
        )
    raise PaymentMethodNotAllowedError(message)
