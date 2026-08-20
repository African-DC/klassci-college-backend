"""Corbeille : archiver d'abord, supprimer ensuite.

Les fiches qui portent une histoire — un élève, un parent, un enseignant, un
membre du personnel, une inscription — sont liées à des personnes réelles et à
des années de données. On ne les efface pas d'un clic.

Deux temps, donc. **Archiver** retire la fiche de tous les écrans sans rien
détruire : c'est réversible, et c'est ce qui permet de corriger une erreur de
manipulation le lendemain. **Supprimer définitivement** ne se fait que depuis
la corbeille, sur une fiche déjà archivée, et ne se rattrape pas.

Chaque étape exige un motif. Sans lui, le journal dirait qu'une fiche a
disparu sans dire pourquoi, ce qui ne vaut guère mieux que pas de trace.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column


class ArchivableMixin:
    """Colonnes de corbeille, partagées par les fiches qui en relèvent.

    `archived_at` est la seule source de vérité : une fiche est dans la
    corbeille si et seulement si cette date est renseignée. Un booléen séparé
    finirait par diverger de la date, et on ne saurait plus lequel croire.
    """

    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    archived_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None
