"""Les fiches archivées disparaissent de toutes les requêtes, sans exception.

Quarante-neuf requêtes visent les cinq entités concernées. Ajouter
`archived_at IS NULL` à chacune reviendrait à parier qu'on n'en oublie
aucune — et il suffit d'un oubli pour qu'une fiche mise à la corbeille
réapparaisse dans un écran, ce qui est précisément ce que la corbeille
promet d'éviter.

La règle est donc posée une fois, sur la session : toute lecture d'une entité
archivable est filtrée, y compris quand elle est chargée à travers une
relation. Un écran qui veut voir la corbeille le demande explicitement.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.models.enrollment import Enrollment
from app.models.user import Parent, StaffProfile, Student, TeacherProfile

#: Option d'exécution qui lève le filtre. Nommée plutôt que booléenne nue
#: pour qu'on la retrouve en cherchant dans le code.
INCLUDE_ARCHIVED = "include_archived"

_ARCHIVABLE = (Student, Parent, TeacherProfile, StaffProfile, Enrollment)


def register_archive_filter() -> Callable[[Any], None]:
    """Branche le filtre sur toutes les sessions ORM.

    Rend l'ecouteur pose, pour que le test qui verifie ce filtre puisse le
    retirer ensuite : il est branche sur la classe `Session` entiere, donc
    le laisser en place changerait le comportement de tous les tests qui
    suivent dans le meme processus.
    """

    @event.listens_for(Session, "do_orm_execute")
    def _hide_archived(execute_state: Any) -> None:
        if not execute_state.is_select:
            return
        # Un rechargement de colonne porte sur une ligne déjà identifiée :
        # la filtrer ferait échouer un accès légitime à une fiche qu'on vient
        # justement d'archiver.
        if execute_state.is_column_load:
            return
        if execute_state.execution_options.get(INCLUDE_ARCHIVED, False):
            return

        for model in _ARCHIVABLE:
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    model,
                    lambda cls: cls.archived_at.is_(None),
                    include_aliases=True,
                )
            )

    return _hide_archived
