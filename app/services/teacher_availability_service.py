"""Disponibilités déclarées d'un enseignant.

Le modèle, sa table et son dépôt existaient depuis la première migration, et
le générateur automatique d'emploi du temps les consultait déjà. Mais rien ne
permettait de les saisir : ni l'enseignant pour dire quand il n'est pas là, ni
le secrétariat pour le noter quand on le lui a dit de vive voix. Une donnée que
personne ne peut saisir reste vide, et une contrainte toujours vide ne
contraint rien.

Trois lectures, et la distinction est délibérée :

- l'administration gère les plages de n'importe quel enseignant, sous
  `timetable:write` — chez ROSTAN c'est le directeur des études, ailleurs le
  secrétariat, d'où une permission et non un rôle en dur ;
- l'enseignant gère **les siennes**, sous `timetable:availability:self_declare`,
  avec un contrôle de propriétaire à chaque écriture ;
- tout le monde consulte la semaine d'un enseignant **avant** de poser un
  créneau : les cours déjà placés dans les autres classes, et les plages qu'il
  a lui-même fermées. Voir avant de se tromper vaut mieux qu'un refus après.
"""

from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.timetable import TeacherAvailability
from app.repositories import admin_repository
from app.repositories import timetable_repository as repo
from app.schemas.timetable import (
    TeacherAvailabilityCreate,
    TeacherAvailabilityResponse,
    TeacherAvailabilityUpdate,
    TeacherWeekBusySlot,
    TeacherWeekOpenSlot,
    TeacherWeekResponse,
)


def _parse_time(valeur: str, champ: str) -> time:
    """Lit une heure « HH:MM » en refusant clairement ce qui n'en est pas une."""
    try:
        heures, minutes = valeur.split(":")
        return time(int(heures), int(minutes))
    except (ValueError, AttributeError) as exc:
        raise BusinessValidationError(
            f"{champ} doit être une heure au format HH:MM, reçu « {valeur} »."
        ) from exc


def _to_response(av: TeacherAvailability) -> TeacherAvailabilityResponse:
    return TeacherAvailabilityResponse(
        id=av.id,
        teacher_id=av.teacher_id,
        day=av.day,
        start_time=av.start_time.strftime("%H:%M"),
        end_time=av.end_time.strftime("%H:%M"),
        available=av.available,
        preferred=av.preferred,
    )


async def _get_owned(
    db: AsyncSession, av_id: int, *, teacher_id: int | None
) -> TeacherAvailability:
    """Charge une plage, et la masque quand elle appartient à un collègue.

    `teacher_id` à None vaut « l'administration », qui les voit toutes. Sinon le
    contrôle porte sur le propriétaire et pas seulement sur l'existence : sans
    lui, un enseignant rouvrirait les indisponibilités d'un autre en devinant un
    identifiant. On répond introuvable plutôt qu'interdit, pour ne pas confirmer
    au passage qu'une plage existe chez quelqu'un d'autre.
    """
    av = await repo.get_teacher_availability_by_id(db, av_id)
    if av is None or (teacher_id is not None and av.teacher_id != teacher_id):
        raise NotFoundError("TeacherAvailability", av_id)
    return av


async def list_for_teacher(db: AsyncSession, teacher_id: int) -> list[TeacherAvailabilityResponse]:
    """Les plages déclarées pour un enseignant."""
    return [_to_response(av) for av in await repo.list_teacher_availabilities(db, teacher_id)]


async def create(
    db: AsyncSession, teacher_id: int, data: TeacherAvailabilityCreate
) -> TeacherAvailabilityResponse:
    """Enregistre une plage de disponibilité ou d'indisponibilité."""
    debut = _parse_time(data.start_time, "L'heure de début")
    fin = _parse_time(data.end_time, "L'heure de fin")
    if debut >= fin:
        raise BusinessValidationError("L'heure de fin doit être après l'heure de début.")

    av = await repo.create_teacher_availability(
        db,
        teacher_id=teacher_id,
        day=data.day.value,
        start_time=debut,
        end_time=fin,
        available=data.available,
        preferred=data.preferred,
    )
    await db.commit()
    refreshed = await repo.get_teacher_availability_by_id(db, av.id)
    assert refreshed is not None
    return _to_response(refreshed)


async def update(
    db: AsyncSession,
    av_id: int,
    data: TeacherAvailabilityUpdate,
    *,
    teacher_id: int | None = None,
) -> TeacherAvailabilityResponse:
    """Rouvre ou referme une plage existante."""
    av = await _get_owned(db, av_id, teacher_id=teacher_id)
    await repo.update_teacher_availability(
        db,
        av,
        available=data.available,
        preferred=data.preferred,
    )
    await db.commit()
    refreshed = await repo.get_teacher_availability_by_id(db, av_id)
    assert refreshed is not None
    return _to_response(refreshed)


async def remove(db: AsyncSession, av_id: int, *, teacher_id: int | None = None) -> None:
    """Retire une plage."""
    av = await _get_owned(db, av_id, teacher_id=teacher_id)
    await repo.delete_teacher_availability(db, av)
    await db.commit()


async def week_for_teacher(
    db: AsyncSession, teacher_id: int, *, academic_year_id: int | None = None
) -> TeacherWeekResponse:
    """La semaine d'un enseignant, telle qu'elle contraint la saisie d'un creneau.

    Une seule reponse pour les cours et les plages fermees, parce que celui qui
    pose un creneau se moque de la nature de l'empechement : il veut savoir ou
    il ne peut pas poser. La nature reste portee par `kind`, pour que l'ecran
    puisse le dire — un cours se deplace, une indisponibilite se discute avec
    l'interesse.

    `open` et `has_declarations` portent l'autre moitie de la regle : la table
    se lit en liste blanche des qu'une plage a ete declaree. Sans eux, l'ecran
    montrerait une semaine presque vide la ou la creation sera refusee partout
    sauf sur deux matinees.
    """
    prof = await repo.get_teacher_profile(db, teacher_id)
    if prof is None:
        raise NotFoundError("TeacherProfile", teacher_id)

    annee = academic_year_id or await admin_repository.get_current_academic_year_id(db)
    plages = await repo.list_teacher_availabilities(db, teacher_id)

    occupes = [
        TeacherWeekBusySlot(
            day=slot.day,
            start_time=slot.start_time.strftime("%H:%M"),
            end_time=slot.end_time.strftime("%H:%M"),
            kind="course",
            label=slot.subject.name if slot.subject else "Cours",
            class_name=slot.class_.name if slot.class_ else None,
        )
        for slot in await repo.list_slots(db, teacher_id=teacher_id, academic_year_id=annee)
    ]
    occupes += [
        TeacherWeekBusySlot(
            day=av.day,
            start_time=av.start_time.strftime("%H:%M"),
            end_time=av.end_time.strftime("%H:%M"),
            kind="unavailable",
            label="Indisponible",
            class_name=None,
        )
        for av in plages
        if not av.available
    ]
    occupes.sort(key=lambda s: (s.day, s.start_time))

    ouvertes = sorted(
        (
            TeacherWeekOpenSlot(
                day=av.day,
                start_time=av.start_time.strftime("%H:%M"),
                end_time=av.end_time.strftime("%H:%M"),
                preferred=av.preferred,
            )
            for av in plages
            if av.available
        ),
        key=lambda s: (s.day, s.start_time),
    )

    return TeacherWeekResponse(
        teacher_id=teacher_id,
        teacher_name=f"{prof.first_name} {prof.last_name}".strip(),
        has_declarations=bool(ouvertes),
        busy=occupes,
        open=ouvertes,
    )
