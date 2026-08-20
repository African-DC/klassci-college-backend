"""Chapitre III — personnel enseignant : tableaux 18 à 21.

KLASSCI connaît l'identité, la discipline, le service et les deux numéros
administratifs de chaque enseignant. Il ne connaît en revanche ni leur sexe,
ni leur diplôme, ni leur type de contrat, ni leur date de prise de service :
les colonnes correspondantes sortent vides et signalées, et les tableaux 19
et 21, qui reposent entièrement sur ces informations, sont livrés à remplir
à la main.
"""

from __future__ import annotations

from app.services.deep_report import _format as fmt
from app.services.deep_report._context import ReportContext
from app.services.deep_report._metrics import Cycle
from app.services.deep_report._types import (
    MISSING,
    PENDING_NOTE,
    HeaderGroup,
    ReportRow,
    ReportTable,
    simple_headers,
)

# Codes disciplines du canevas, avec les libellés de matières qui s'y
# rattachent. La correspondance se fait sur un fragment de nom normalisé :
# une école écrit « Histoire-Géographie », une autre « Hist-Géo ».
_DISCIPLINE_CODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("FR", ("francais", "lettres")),
    ("HG", ("histoire", "geographie", "histgeo", "histoiregeo")),
    ("ANG", ("anglais",)),
    ("PHILO", ("philosophie", "philo")),
    ("ALL", ("allemand",)),
    ("ESP", ("espagnol",)),
    ("MATHS", ("mathematiques", "maths", "math")),
    ("SVT", ("sciencesdelavie", "svt", "biologie")),
    ("EDHC", ("edhc", "droitsdelhomme", "citoyennete")),
    ("AP", ("artsplastiques", "arts", "dessin")),
    ("SP", ("sciencesphysiques", "physiquechimie", "physique", "chimie")),
    ("EPS", ("educationphysique", "eps", "sport")),
    ("INFOR", ("informatique", "tic", "numerique")),
    ("FHR", ("formationhumaine", "religieuse", "fhr")),
)

_TEACHER_MISSING_NOTE = (
    "Colonnes « Sexe », « Date et lieu de naissance », « Diplôme », « Type de contrat » "
    f"et « Date de prise de service » : non collectées par KLASSCI — {PENDING_NOTE.lower()}."
)


def _normalise(label: str) -> str:
    lowered = label.strip().lower()
    for accented, plain in (
        ("é", "e"),
        ("è", "e"),
        ("ê", "e"),
        ("à", "a"),
        ("î", "i"),
        ("ï", "i"),
        ("ô", "o"),
        ("û", "u"),
        ("ç", "c"),
    ):
        lowered = lowered.replace(accented, plain)
    return "".join(char for char in lowered if char.isalnum())


def _code_of_subject(subject_name: str) -> str | None:
    """Code canevas d'une matière, ou None si elle n'entre dans aucune case."""
    normalised = _normalise(subject_name)
    for code, keywords in _DISCIPLINE_CODES:
        if any(keyword in normalised for keyword in keywords):
            return code
    return None


def build_tables(context: ReportContext) -> tuple[ReportTable, ...]:
    """Tableaux 18 à 21."""
    return (
        _teachers_table(context),
        _contract_table(),
        _discipline_table(context),
        _discipline_by_gender_table(),
    )


def _teachers_table(context: ReportContext) -> ReportTable:
    """Tableau 18 — situation nominative des enseignants."""
    rows: list[ReportRow] = []
    for index, teacher in enumerate(context.teachers, start=1):
        subjects = sorted(context.staffing.subjects_by_teacher.get(teacher.id, set()))
        classes = sorted(context.staffing.classes_by_teacher.get(teacher.id, set()))
        rows.append(
            ReportRow(
                cells=(
                    str(index),
                    f"{teacher.last_name} {teacher.first_name}".strip(),
                    MISSING,  # Sexe — non collecté
                    MISSING,  # Date et lieu de naissance — non collectés
                    MISSING,  # Diplôme — non collecté
                    fmt.text(", ".join(subjects) or teacher.speciality),
                    MISSING,  # Type de contrat — non collecté
                    MISSING,  # Date de prise de service — non collectée
                    fmt.text(teacher.cnps_number),
                    fmt.text(teacher.teaching_authorization_number),
                    fmt.text(", ".join(classes)),
                    MISSING,  # Observations — à porter à la main
                )
            )
        )

    return ReportTable(
        number=18,
        title="Situation des enseignants",
        groups=simple_headers(
            "N°",
            "Nom et Prénoms",
            "Sexe",
            "Date et lieu de naissance",
            "Diplôme",
            "Discipline",
            "Type de contrat",
            "Date de prise de service",
            "N° CNPS",
            "N° autorisation d'enseigner",
            "Classes tenues",
            "Observations",
        ),
        rows=tuple(rows),
        note=_TEACHER_MISSING_NOTE,
        empty_message="Aucun enseignant enregistré.",
    )


def _contract_table() -> ReportTable:
    """Tableau 19 — synthèse par type de contrat, hors de portée de KLASSCI."""
    return ReportTable(
        number=19,
        title="Synthèse des enseignants par type de contrat",
        groups=(
            HeaderGroup("Type de contrat"),
            HeaderGroup("1er cycle", subs=("F", "G", "T"), align="center"),
            HeaderGroup("2nd cycle", subs=("F", "G", "T"), align="center"),
            HeaderGroup("Total", subs=("F", "G", "T"), align="center"),
        ),
        pending=True,
        note=(
            "Le type de contrat et le sexe des enseignants ne sont pas enregistrés dans "
            f"KLASSCI : ce tableau est laissé vide, {PENDING_NOTE.lower()}. Aucun zéro "
            "n'est porté, un effectif nul se lirait comme un constat."
        ),
        empty_message=f"{PENDING_NOTE} — données non collectées.",
    )


def _discipline_table(context: ReportContext) -> ReportTable:
    """Tableau 20 — enseignants par discipline et par cycle (1 = 1er, 2 = 2nd)."""
    groups = (
        HeaderGroup("Établissement"),
        *(
            HeaderGroup(code, subs=("1", "2"), align="center")
            for code, _keywords in _DISCIPLINE_CODES
        ),
        HeaderGroup("TOTAL", subs=("1", "2"), align="center"),
    )

    # On regroupe d'abord les libellés de matières par code du canevas, pour
    # ne compter chaque enseignant qu'une fois par code et par cycle.
    subjects_by_code: dict[str, list[str]] = {code: [] for code, _kw in _DISCIPLINE_CODES}
    unmapped: set[str] = set()
    for subject_name in context.staffing.subject_names:
        code = _code_of_subject(subject_name)
        if code is None:
            unmapped.add(subject_name)
        else:
            subjects_by_code[code].append(subject_name)

    cells: list[str] = ["Effectif enseignant"]
    totals = {Cycle.FIRST: set[int](), Cycle.SECOND: set[int]()}
    for code, _keywords in _DISCIPLINE_CODES:
        names = tuple(subjects_by_code[code])
        for cycle in (Cycle.FIRST, Cycle.SECOND):
            cells.append(str(context.staffing.count(names, cycle)))
            for name in names:
                totals[cycle] |= context.staffing.by_subject_cycle.get((name, cycle), set())
    cells.extend([str(len(totals[Cycle.FIRST])), str(len(totals[Cycle.SECOND]))])

    notes = [
        "Colonnes « 1 » et « 2 » : premier et second cycle. Un enseignant intervenant "
        "sur les deux cycles est compté dans chacun."
    ]
    if unmapped:
        notes.append(
            "Matières hors nomenclature du canevas, non comptées ici : "
            f"{', '.join(sorted(unmapped))} — {PENDING_NOTE.lower()}."
        )

    return ReportTable(
        number=20,
        title="Enseignants par discipline",
        groups=groups,
        rows=(ReportRow(cells=tuple(cells)),) if context.staffing.subject_names else (),
        note=" ".join(notes),
        empty_message=(
            "Aucun emploi du temps saisi pour cette année : la répartition par discipline "
            f"ne peut pas être établie — {PENDING_NOTE.lower()}."
        ),
    )


def _discipline_by_gender_table() -> ReportTable:
    """Tableau 21 — même grille par sexe, impossible faute de donnée."""
    groups = (
        HeaderGroup("Établissement"),
        *(
            HeaderGroup(code, subs=("F", "G"), align="center")
            for code, _keywords in _DISCIPLINE_CODES
        ),
        HeaderGroup("TOTAL", subs=("F", "G"), align="center"),
    )
    return ReportTable(
        number=21,
        title="Enseignants par discipline et par sexe",
        groups=groups,
        pending=True,
        note=(
            "Le sexe des enseignants n'est pas enregistré dans KLASSCI : ce tableau est "
            f"laissé vide, {PENDING_NOTE.lower()}."
        ),
        empty_message=f"{PENDING_NOTE} — sexe des enseignants non collecté.",
    )
