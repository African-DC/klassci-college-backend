"""Schémas de la corbeille."""

from datetime import datetime

from pydantic import BaseModel


class ArchivedEntryResponse(BaseModel):
    """Une fiche mise de côté : laquelle, quand, par qui, et pourquoi.

    Le motif et le nom de l'auteur ne sont pas décoratifs : sans eux, l'écran
    dirait qu'une fiche a disparu sans dire qui s'en est chargé ni pourquoi,
    et la personne qui hésite devant le bouton « restaurer » n'aurait aucun
    élément pour trancher.
    """

    entity_type: str
    entity_id: int
    label: str
    archived_at: datetime
    archived_by: int | None
    # Résolu à la lecture depuis les fiches ; absent si le compte auteur n'a
    # plus de fiche à son nom.
    archived_by_name: str | None
    reason: str | None


class ArchiveListResponse(BaseModel):
    items: list[ArchivedEntryResponse]
    total: int
    page: int
    size: int
