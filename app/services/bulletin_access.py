"""Porte d'entree des portails vers un bulletin : l'appartenance, pas le droit d'admin.

Le bulletin d'un eleve est un document de sa famille. Mais la route
d'administration qui le delivre est gardee par `reports:read`, un droit qui
ouvre les bulletins de **toute l'ecole** : le donner a un eleve ou a un parent
pour qu'il telecharge le sien reviendrait a lui ouvrir ceux des autres.

Les portails passent donc par ici. La question posee n'est pas « avez-vous le
droit de lire les bulletins », mais « ce bulletin est-il le votre », et
« est-il publie ».
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.grade import Bulletin


async def ensure_owned_and_published(
    db: AsyncSession, bulletin_id: int, *, student_id: int
) -> None:
    """Laisse passer le bulletin publie de cet eleve, refuse tout le reste en 404.

    Trois refus, une seule reponse — « ce bulletin n'existe pas » :

    - le bulletin n'existe pas ;
    - il existe mais appartient a un camarade ;
    - il existe, il est bien le sien, mais il n'est pas encore publie.

    Repondre 403 sur le deuxieme cas distinguerait « il existe mais il n'est
    pas a vous » de « il n'existe pas », et suffirait a qui incremente des
    identifiants pour cartographier les bulletins de l'ecole. Le troisieme cas
    suit la meme regle : un portail ne montre que les bulletins publies, et si
    deviner un identifiant permettait d'en tirer le PDF, la publication ne
    serait plus qu'un affichage.
    """
    row = (
        await db.execute(
            select(Bulletin.student_id, Bulletin.is_published).where(Bulletin.id == bulletin_id)
        )
    ).first()

    if row is None:
        raise NotFoundError("Bulletin", bulletin_id)

    owner_id, is_published = int(row[0]), bool(row[1])
    if owner_id != student_id or not is_published:
        raise NotFoundError("Bulletin", bulletin_id)
