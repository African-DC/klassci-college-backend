"""Composition d'annuaires enseignants collège, source unique PDF/Word/Excel.

Deux sources sans rapprochement heuristique :
- fiches enseignants (annuaire) ;
- matières déclarées, et affectations de l'emploi du temps pour l'année
  sélectionnée. Une matière homonyme garde son ID/niveau/série.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import AcademicYear, Class, Level, Series, Subject
from app.models.timetable import TimetableSlot
from app.models.user import TeacherProfile, User
from app.services._school_settings_helper import load_school_settings_for_pdf

COLUMNS = {
    "name": "Nom et prénoms", "speciality": "Spécialité",
    "subject": "Matière", "class": "Classe", "level": "Niveau",
    "series": "Série", "contract": "Contrat", "genre": "Sexe",
    "phone": "Téléphone", "email": "Email", "source": "Origine",
}
GROUPS = {"none": "Sans regroupement", "subject": "Par matière",
          "class": "Par classe", "level": "Par niveau", "series": "Par série",
          "speciality": "Par spécialité", "contract": "Par contrat"}
DEFAULTS = ["name", "speciality", "contract", "phone"]
MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class Selection:
    year_id: int | None
    class_ids: list[int]
    level_ids: list[int]
    series_ids: list[int]
    subject_ids: list[int]
    columns: list[str]
    group: str
    orientation: Literal["auto", "portrait", "landscape"]
    mode: Literal["directory", "assignments"]

    def validate(self) -> None:
        if not self.columns or len(set(self.columns)) != len(self.columns) or any(c not in COLUMNS for c in self.columns):
            raise HTTPException(422, "Choisissez au moins une colonne valide et sans doublon.")
        if self.group not in GROUPS:
            raise HTTPException(422, "Regroupement inconnu.")
        if self.mode not in ("directory", "assignments"):
            raise HTTPException(422, "Document inconnu.")
        if self.mode == "assignments" and self.year_id is None:
            raise HTTPException(422, "Sélectionnez une année scolaire pour les affectations.")
        if self.mode == "directory" and (self.class_ids or self.level_ids or self.series_ids or self.subject_ids or self.group in ("subject", "class", "level", "series")):
            raise HTTPException(422, "Pour filtrer par classe, matière ou niveau, sélectionnez « Enseignants par affectation ».")
        if self.group != "none" and self.group not in self.columns and self.mode == "assignments":
            pass  # le titre du groupe remplace sa colonne
        if self.group == "none" and self.mode == "assignments" and not any(
            c in self.columns for c in ("subject", "class", "level")
        ) and len(self.columns) == 1:
            raise HTTPException(422, "Sans regroupement, ajoutez une colonne de contexte pour les affectations.")


def choose_orientation(selection: Selection) -> str:
    weights = {"name": 54, "speciality": 40, "subject": 41, "class": 28,
               "level": 27, "series": 18, "contract": 24, "genre": 15,
               "phone": 33, "email": 45, "source": 32}
    width = sum(weights[c] for c in selection.columns)
    if width > 265 or (selection.orientation == "portrait" and width > 180):
        raise HTTPException(422, "Trop de colonnes pour ce format A4 : retirez-en ou utilisez le paysage.")
    return ("landscape" if width > 180 else "portrait") if selection.orientation == "auto" else selection.orientation


def _contract(t: TeacherProfile) -> str:
    v = getattr(t.contract_type, "value", t.contract_type)
    return {"permanent": "Permanent", "vacataire": "Vacataire", "fonctionnaire": "Fonctionnaire"}.get(v, "—")


def _teacher(t: TeacherProfile, user: User | None) -> dict[str, str]:
    return {"name": " ".join(x for x in (t.last_name, t.first_name) if x).strip(),
            "speciality": t.speciality or "—", "contract": _contract(t),
            "genre": t.genre or "—", "phone": t.phone or "—",
            "email": user.email if user else "—",
            "subject": "—", "class": "—", "level": "—",
            "series": "—", "source": "Fiche enseignant"}


async def filters(db: AsyncSession) -> dict:
    years = (await db.execute(select(AcademicYear).order_by(AcademicYear.id.desc()))).scalars().all()
    classes = (await db.execute(select(Class).order_by(Class.name))).scalars().all()
    levels = (await db.execute(select(Level).order_by(Level.order, Level.name))).scalars().all()
    series = (await db.execute(select(Series).order_by(Series.name))).scalars().all()
    subjects = (await db.execute(select(Subject).order_by(Subject.name))).scalars().all()
    return {
        "years": [{"id": a.id, "name": a.name, "current": bool(a.is_current)} for a in years],
        "classes": [{"id": c.id, "name": c.name, "level_id": c.level_id, "series_id": c.series_id} for c in classes],
        "levels": [{"id": a.id, "name": a.name} for a in levels],
        "series": [{"id": a.id, "name": a.name, "level_id": a.level_id} for a in series],
        "subjects": [{"id": a.id, "name": a.name, "level_id": a.level_id, "series_id": a.series_id} for a in subjects],
        "columns": COLUMNS, "groups": GROUPS,
    }


async def load(db: AsyncSession, s: Selection) -> tuple[dict, list[dict]]:
    s.validate()
    teachers = (await db.execute(select(TeacherProfile))).scalars().all()
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_([t.user_id for t in teachers])))).scalars().all()} if teachers else {}
    by_id = {t.id: _teacher(t, users.get(t.user_id)) for t in teachers}
    school = await load_school_settings_for_pdf(db)
    if s.mode == "directory":
        if s.group not in ("none", "speciality", "contract"):
            raise HTTPException(422, "Cette classification exige le document « Affectations ».")
        rows = [{**info, "_id": str(i)} for i, info in by_id.items()]
    else:
        if s.year_id is None:
            raise HTTPException(422, "Année scolaire obligatoire.")
        rows = []
        # Créneaux : relation classe-matière-enseignant explicite et datée.
        query = (select(TimetableSlot.teacher_id, TimetableSlot.subject_id, TimetableSlot.class_id,
                        Class.name, Level.name, Series.name, Subject.name)
            .join(Class, Class.id == TimetableSlot.class_id)
            .join(Level, Level.id == Class.level_id)
            .outerjoin(Series, Series.id == Class.series_id)
            .join(Subject, Subject.id == TimetableSlot.subject_id)
            .where(TimetableSlot.academic_year_id == s.year_id))
        if s.class_ids: query = query.where(Class.id.in_(s.class_ids))
        if s.level_ids: query = query.where(Class.level_id.in_(s.level_ids))
        if s.series_ids: query = query.where(Class.series_id.in_(s.series_ids))
        if s.subject_ids: query = query.where(Subject.id.in_(s.subject_ids))
        seen = set()
        for tid, sid, cid, cn, ln, sn, sub in (await db.execute(query)).all():
            if tid not in by_id: continue
            key = (tid, sid, cid)
            if key in seen: continue
            seen.add(key)
            rows.append({**by_id[tid], "_id": str(tid),
                "_subject_id": str(sid), "_class_id": str(cid),
                "subject": sub, "class": cn, "level": ln,
                "series": sn or "Sans série", "source": "Emploi du temps"})
        # Les enseignants affectés seulement sur la fiche matière, sans créneau,
        # restent visibles au niveau de la matière : pas de classe inventée.
        subjects = (await db.execute(select(Subject).where(Subject.teacher_id.is_not(None)))).scalars().all()
        for sub in subjects:
            if sub.teacher_id not in by_id: continue
            if s.subject_ids and sub.id not in s.subject_ids: continue
            if s.level_ids and sub.level_id not in s.level_ids: continue
            if s.series_ids and sub.series_id not in s.series_ids: continue
            if s.class_ids: continue  # une fiche matière n'identifie aucune classe
            key = (sub.teacher_id, sub.id, None)
            if key in seen: continue
            seen.add(key)
            rows.append({**by_id[sub.teacher_id], "_id": str(sub.teacher_id),
                "_subject_id": str(sub.id), "_class_id": "",
                "subject": sub.name, "class": "Non précisée",
                "level": "Non précisé", "series": "Non précisée",
                "source": "Fiche matière"})
    if len(rows) > 12000:
        raise HTTPException(422, "Sélection trop large : réduisez les critères.")
    rows.sort(key=lambda x: (x["name"].casefold(), x["subject"].casefold(), x["class"].casefold()))
    return school, rows


def compose(rows: list[dict], s: Selection) -> list[tuple[str, list[list[str]]]]:
    groups: dict[str, list[list[str]]] = defaultdict(list)
    duplicates: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for row in rows:
        title = row[s.group] if s.group != "none" else "Enseignants"
        # Ne pas fusionner des matières ou classes homonymes d'IDs différents.
        if s.group == "subject":
            title += f" · matière #{row.get('_subject_id', '')}"
        if s.group == "class":
            title += f" · classe #{row.get('_class_id', '')}"
        values = tuple(str(row[c]) for c in s.columns)
        if values in duplicates[title]: continue
        duplicates[title].add(values)
        groups[title].append(list(values))
    return sorted(groups.items(), key=lambda x: x[0].casefold())


def render_pdf(s: Selection, school: dict, rows: list[dict]) -> bytes:
    from weasyprint import HTML
    from app.services.pdf import components as ui
    from app.services.pdf.theme import PDFTheme
    theme = PDFTheme.from_school(school)
    orientation = choose_orientation(s)
    headers = [{"label": COLUMNS[c]} for c in s.columns]
    groups = compose(rows, s)
    sections = []
    for title, records in groups:
        sections.append(f'<h2 style="font-size:12px;color:var(--primary);margin:14px 0 6px">{ui.esc(title)}</h2>')
        sections.append(ui.premium_table(headers=headers, rows=records, theme=theme, empty_message="Aucun enseignant"))
    if not sections: sections = ['<p>Aucun enseignant pour les critères choisis.</p>']
    html = (f'<html lang="fr"><head><meta charset="UTF-8">'
        + ui.base_styles(theme, page_size="A4 "+orientation, margin="15mm", paginate=True)
        + '</head><body>' + ui.page_decoration(theme=theme, watermark_text=school.get("school_name") or "")
        + '<div class="pdf-page-body">'
        + ui.premium_header(school, theme=theme, doc_type="LISTE DES ENSEIGNANTS",
            doc_subtitle="Annuaire" if s.mode == "directory" else "Affectations pédagogiques")
        + ui.meta_banner(f"<strong>{len(rows)} entrée(s)</strong>",
            "<span>Liste générée depuis KLASSCI Collège</span>", theme=theme)
        + "".join(sections)
        + ui.premium_footer(school, theme=theme, note="Document administratif interne.")
        + "</div></body></html>")
    return HTML(string=html).write_pdf()


def render_docx(s: Selection, school: dict, rows: list[dict]) -> bytes:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm, RGBColor
    from app.services.pdf._helpers import image_bytes
    from app.services.pdf.theme import PDFTheme
    theme = PDFTheme.from_school(school)
    orient = choose_orientation(s)
    doc = Document()
    sec = doc.sections[0]
    if orient == "landscape":
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = Cm(29.7), Cm(21)
    sec.left_margin = sec.right_margin = Cm(1.3)
    logo = image_bytes(school.get("logo_url"))
    if logo and logo[1] in ("image/png", "image/jpeg", "image/jpg"):
        try: doc.add_paragraph().add_run().add_picture(BytesIO(logo[0]), width=Cm(2))
        except (OSError, ValueError): pass
    title = doc.add_heading(school.get("school_name") or "Établissement", 0)
    title.runs[0].font.color.rgb = RGBColor.from_string(theme.primary.lstrip("#").upper())
    doc.add_heading("LISTE DES ENSEIGNANTS", 1)
    doc.add_paragraph("Annuaire" if s.mode == "directory" else "Affectations pédagogiques")
    for label, lines in compose(rows, s):
        doc.add_heading(label, 2)
        table = doc.add_table(rows=1, cols=len(s.columns))
        table.style = "Light Shading Accent 1"
        for i, col in enumerate(s.columns): table.rows[0].cells[i].text = COLUMNS[col]
        for row in lines:
            cells = table.add_row().cells
            for i, val in enumerate(row): cells[i].text = val
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def render_xlsx(s: Selection, school: dict, rows: list[dict]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from app.services.exports._workbook_branding import write_header, style_table_header, setup_printing
    from app.services.pdf.theme import PDFTheme
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "Enseignants"
    start = write_header(ws, school, title="LISTE DES ENSEIGNANTS",
        subtitle="Annuaire" if s.mode == "directory" else "Affectations pédagogiques",
        meta_lines=[f"{len(rows)} entrée(s)"], width=len(s.columns))
    ws.append([]) if ws.max_row < start else None
    for idx, col in enumerate(s.columns, 1): ws.cell(start, idx, COLUMNS[col])
    style_table_header(ws, start, len(s.columns), school)
    line = start + 1
    for title, records in compose(rows, s):
        ws.cell(line, 1, title)
        ws.cell(line, 1).font = Font(bold=True)
        line += 1
        for record in records:
            for idx, value in enumerate(record, 1):
                # Prévenir l'injection de formules CSV/XLSX provenant des fiches.
                safe = "'" + value if value.startswith(("=", "+", "-", "@")) else value
                ws.cell(line, idx, safe)
            line += 1
    for idx, col in enumerate(s.columns, 1):
        ws.column_dimensions[get_column_letter(idx)].width = min(45, max(14, len(COLUMNS[col]) + 9))
    ws.freeze_panes = f"A{start+1}"
    setup_printing(ws, header_row=start, landscape=choose_orientation(s) == "landscape")
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
