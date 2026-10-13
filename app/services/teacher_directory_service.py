"""Répertoire des enseignants : une lecture canonique pour PDF, Word et Excel.

Deux provenances complémentaires, jamais déduites l'une de l'autre :
- Emploi du temps : affectation classe/matière de l'année demandée.
- Référentiel : Subject.teacher_id par niveau/série, sans inventer de classe
  ni rattacher cette affectation à l'année scolaire.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import AcademicYear, Class, Level, Series, Subject
from app.models.timetable import Timetable, TimetableSlot
from app.models.user import TeacherProfile, User
from app.schemas.teacher_directory import COLUMNS, GROUPS, TeacherExportOptions


CONTRACT_LABELS = {
    "permanent": "Permanent", "vacataire": "Vacataire", "fonctionnaire": "Fonctionnaire"
}


def normalize(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def teacher_row(teacher: TeacherProfile, email: str | None) -> dict[str, str]:
    raw_contract = getattr(teacher.contract_type, "value", teacher.contract_type)
    return {
        "name": f"{teacher.last_name} {teacher.first_name}".strip(),
        "speciality": teacher.speciality or "—",
        "subject": "—",
        "class": "—",
        "level": "—",
        "series": "—",
        "contract": CONTRACT_LABELS.get(raw_contract, "—"),
        "gender": teacher.genre or "—",
        "phone": teacher.phone or "—",
        "email": email or "—",
        "source": "Sans affectation",
        "cnps": teacher.cnps_number or "—",
        "authorization": teacher.teaching_authorization_number or "—",
        "_teacher_id": str(teacher.id),
        "_subject_id": "", "_class_id": "", "_level_id": "", "_series_id": "",
    }


def compose_groups(
    rows: list[dict[str, str]], options: TeacherExportOptions
) -> list[dict[str, Any]]:
    """OR dans chaque filtre, AND entre filtres ; aucune fusion de matière homonyme."""
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        field = options.group_by
        label = ("Enseignants sélectionnés" if field == "none" else row.get(field, "—")) or "—"
        identity = row.get({
            "subject": "_subject_id", "class": "_class_id",
            "level": "_level_id", "series": "_series_id",
        }.get(field, ""), "")
        key = f"{field}|{identity}|{normalize(label)}"
        if key not in grouped:
            grouped[key] = {"title": label, "identity": identity, "rows": [], "_seen": set()}
        vals = [row.get(col, "—") for col in options.columns]
        # « Nom seul par matière » = une occurrence du nom dans la rubrique.
        # Si les colonnes choisies distinguent deux affectations, on les garde.
        unique = tuple(normalize(v) for v in vals)
        if unique in grouped[key]["_seen"]:
            continue
        grouped[key]["_seen"].add(unique)
        grouped[key]["rows"].append(vals)

    result = sorted(grouped.values(), key=lambda group: normalize(group["title"]))
    title_counts: dict[str, int] = {}
    for group in result:
        title_counts[normalize(group["title"])] = title_counts.get(normalize(group["title"]), 0) + 1
    for group in result:
        if title_counts[normalize(group["title"])] > 1 and group["identity"]:
            group["title"] += f" · Réf. #{group['identity']}"
        group["rows"].sort(key=lambda row: normalize(row[0] if row else ""))
        del group["_seen"], group["identity"]
    return result


async def export_choices(db: AsyncSession) -> dict[str, Any]:
    async def items(model: type, *attributes: str) -> list[dict[str, Any]]:
        records = (await db.execute(select(model).order_by(model.id))).scalars().all()
        return [{key: getattr(obj, key) for key in attributes} for obj in records]

    years = await items(AcademicYear, "id", "name", "is_current")
    levels = await items(Level, "id", "name")
    series = await items(Series, "id", "name", "level_id")
    classes = await items(Class, "id", "name", "level_id", "series_id")
    subjects = await items(Subject, "id", "name", "level_id", "series_id")
    return {
        "years": years, "levels": levels, "series": series,
        "classes": classes, "subjects": subjects,
        "columns": COLUMNS, "groups": GROUPS,
        "default_columns": ["name", "subject", "class", "level"],
    }


async def build_directory(
    db: AsyncSession, options: TeacherExportOptions
) -> dict[str, Any]:
    year_id = options.academic_year_id
    if year_id is not None:
        year = (await db.execute(select(AcademicYear).where(AcademicYear.id == year_id))).scalar_one_or_none()
        if not year:
            raise HTTPException(status_code=422, detail="Année scolaire inconnue.")
    else:
        year = (await db.execute(select(AcademicYear).where(AcademicYear.is_current.is_(True)))).scalars().first()
    # On n'affirme jamais que Subject.teacher_id est daté de cette année.
    if year is None and (options.class_ids or not options.include_catalog):
        raise HTTPException(status_code=422, detail="Sélectionnez une année scolaire pour les affectations de classes.")

    teachers = (await db.execute(
        select(TeacherProfile, User.email)
        .outerjoin(User, User.id == TeacherProfile.user_id)
        .order_by(TeacherProfile.last_name, TeacherProfile.first_name, TeacherProfile.id)
    )).all()
    search = normalize(options.search)
    teacher_base: dict[int, dict[str, str]] = {}
    for teacher, email in teachers:
        contract = getattr(teacher.contract_type, "value", teacher.contract_type)
        if options.contract_types and contract not in options.contract_types:
            continue
        data = teacher_row(teacher, email)
        if search and search not in normalize(data["name"]+" "+data["speciality"]):
            continue
        if options.teacher_ids and teacher.id not in options.teacher_ids:
            continue
        teacher_base[teacher.id] = data

    rows: list[dict[str, str]] = []
    seen: set[tuple[int, int, int, int]] = set()
    covered_by_timetable: set[tuple[int, int]] = set()

    if year:
        statement = (
            select(
                TimetableSlot.teacher_id, TimetableSlot.subject_id, TimetableSlot.class_id,
                Subject.name, Class.name, Level.name, Series.name,
                Class.level_id, Class.series_id,
            )
            .join(Class, Class.id == TimetableSlot.class_id)
            .join(Subject, Subject.id == TimetableSlot.subject_id)
            .join(Level, Level.id == Class.level_id)
            .outerjoin(Series, Series.id == Class.series_id)
            .outerjoin(Timetable, Timetable.id == TimetableSlot.timetable_id)
            .where(TimetableSlot.academic_year_id == year.id)
            .where(or_(Timetable.id.is_(None), Timetable.is_active.is_(True)))
            .order_by(TimetableSlot.teacher_id, TimetableSlot.class_id, TimetableSlot.subject_id)
        )
        if teacher_base:
            statement = statement.where(TimetableSlot.teacher_id.in_(teacher_base.keys()))
        else:
            statement = statement.where(TimetableSlot.teacher_id == -1)
        for teacher_id, subject_id, class_id, subject, klass, level, series, level_id, series_id in (await db.execute(statement)).all():
            key = (int(teacher_id), int(subject_id), int(class_id), int(year.id))
            if key in seen:
                continue
            seen.add(key)
            if (options.class_ids and class_id not in options.class_ids
                or options.level_ids and level_id not in options.level_ids
                or options.series_ids and series_id not in options.series_ids
                or options.subject_ids and subject_id not in options.subject_ids):
                continue
            covered_by_timetable.add((int(teacher_id), int(subject_id)))
            item = dict(teacher_base[teacher_id])
            item.update({
                "subject": subject, "class": klass, "level": level,
                "series": series or "—", "source": f"Emploi du temps {year.name}",
                "_subject_id": str(subject_id), "_class_id": str(class_id),
                "_level_id": str(level_id), "_series_id": str(series_id or ""),
            })
            rows.append(item)

    # Le catalogue n'est PAS la liste des classes : il documente seulement
    # l'enseignant déclaré sur Subject pour un niveau / une série.
    if options.include_catalog and not options.class_ids:
        subjects = (await db.execute(
            select(Subject, Level.name, Series.name)
            .outerjoin(Level, Level.id == Subject.level_id)
            .outerjoin(Series, Series.id == Subject.series_id)
            .where(Subject.teacher_id.is_not(None))
            .order_by(Subject.id)
        )).all()
        for subject, level_name, series_name in subjects:
            tid = subject.teacher_id
            if tid not in teacher_base or (tid, subject.id) in covered_by_timetable:
                continue
            if (options.level_ids and subject.level_id not in options.level_ids
                or options.series_ids and subject.series_id not in options.series_ids
                or options.subject_ids and subject.id not in options.subject_ids):
                continue
            item = dict(teacher_base[tid])
            item.update({
                "subject": subject.name, "class": "—",
                "level": level_name or "—", "series": series_name or "—",
                "source": "Référentiel (hors année)",
                "_subject_id": str(subject.id), "_level_id": str(subject.level_id or ""),
                "_series_id": str(subject.series_id or ""),
            })
            rows.append(item)

    pedagogical = any((options.class_ids, options.level_ids, options.series_ids, options.subject_ids))
    if options.include_unassigned and not pedagogical:
        assigned_ids = {int(item["_teacher_id"]) for item in rows}
        rows.extend(teacher_base[tid] for tid in teacher_base if tid not in assigned_ids)

    if len(rows) > 10000:
        raise HTTPException(status_code=422, detail="Plus de 10 000 affectations. Affinez vos filtres.")

    groups = compose_groups(rows, options)
    return {
        "year": year.name if year else "Non définie",
        "groups": groups, "columns": options.columns,
        "headers": [COLUMNS[key] for key in options.columns],
        "count": sum(len(g["rows"]) for g in groups),
        "teachers_count": len({r["_teacher_id"] for r in rows}),
        "group_by": GROUPS[options.group_by],
    }
