"""Chapitre III — personnel enseignant : tableaux 18 à 21.

KLASSCI connaît l'identité, la discipline, le service et les deux numéros
administratifs de chaque enseignant. Il ne connaît en revanche ni leur sexe,
ni leur diplôme, ni leur type de contrat, ni leur date de prise de service :
les colonnes correspondantes sortent vides et signalées, et les tableaux 19
et 21, qui reposent entièrement sur ces informations, sont livrés à remplir
à la main.
"""

from __future__ import annotations

from app.models.user import TeacherContract
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
        _discipline_by_gender_table(context),
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


def _contract_table(context: ReportContext) -> ReportTable:
    """Tableau 19 — synthèse par type de contrat, ventilée par cycle et par sexe.

    Un enseignant dont le contrat ou le sexe n'est pas renseigné est compté
    dans le total mais dans aucune colonne ventilée, et la note le dit. Le
    ranger arbitrairement dans « vacataire » ou dans « G » ferait dire au
    rapport une chose que personne n'a constatée.
    """
    labels = {
        TeacherContract.PERMANENT: "Permanents",
        TeacherContract.VACATAIRE: "Vacataires",
        TeacherContract.FONCTIONNAIRE: "Fonctionnaires",
    }

    def cycles_of(teacher_id: int) -> set[Cycle]:
        return {
            cycle
            for (_name, cycle), ids in context.staffing.by_subject_cycle.items()
            if teacher_id in ids
        }

    rows: list[ReportRow] = []
    unknown_contract = 0
    unknown_gender = 0
    totals = {"1F": 0, "1G": 0, "1T": 0, "2F": 0, "2G": 0, "2T": 0, "F": 0, "G": 0, "T": 0}

    for contract, label in labels.items():
        counts = dict.fromkeys(totals, 0)
        for teacher in context.teachers:
            if str(getattr(teacher, "contract_type", "") or "") != contract.value:
                continue
            genre = (getattr(teacher, "genre", "") or "").upper()
            cycles = cycles_of(teacher.id)
            counts["T"] += 1
            if genre in ("F", "G"):
                counts[genre] += 1
            for cycle, prefix in ((Cycle.FIRST, "1"), (Cycle.SECOND, "2")):
                if cycle in cycles:
                    counts[f"{prefix}T"] += 1
                    if genre in ("F", "G"):
                        counts[f"{prefix}{genre}"] += 1
        for key in totals:
            totals[key] += counts[key]
        rows.append(
            ReportRow(
                cells=(
                    label,
                    *(str(counts[k]) for k in ("1F", "1G", "1T", "2F", "2G", "2T", "F", "G", "T")),
                )
            )
        )

    for teacher in context.teachers:
        if not getattr(teacher, "contract_type", None):
            unknown_contract += 1
        if (getattr(teacher, "genre", "") or "").upper() not in ("F", "G"):
            unknown_gender += 1

    notes: list[str] = []
    if unknown_contract:
        notes.append(
            f"{unknown_contract} enseignant(s) sans type de contrat renseigné : "
            "absents de ce tableau."
        )
    if unknown_gender:
        notes.append(
            f"{unknown_gender} enseignant(s) sans sexe renseigné : comptés dans les totaux, "
            "dans aucune colonne F ou G."
        )

    return ReportTable(
        number=19,
        title="Synthèse des enseignants par type de contrat",
        groups=(
            HeaderGroup("Type de contrat"),
            HeaderGroup("1er cycle", subs=("F", "G", "T"), align="center"),
            HeaderGroup("2nd cycle", subs=("F", "G", "T"), align="center"),
            HeaderGroup("Total", subs=("F", "G", "T"), align="center"),
        ),
        rows=tuple(rows),
        total_row=ReportRow(
            cells=(
                "TOTAL",
                *(str(totals[k]) for k in ("1F", "1G", "1T", "2F", "2G", "2T", "F", "G", "T")),
            )
        ),
        note=" ".join(notes) if notes else None,
        empty_message="Aucun enseignant enregistré.",
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


def _discipline_by_gender_table(context: ReportContext) -> ReportTable:
    """Tableau 21 — même grille que le 20, ventilée par sexe."""
    groups = (
        HeaderGroup("Établissement"),
        *(
            HeaderGroup(code, subs=("F", "G"), align="center")
            for code, _keywords in _DISCIPLINE_CODES
        ),
        HeaderGroup("TOTAL", subs=("F", "G"), align="center"),
    )

    gender_of = {t.id: (getattr(t, "genre", "") or "").upper() for t in context.teachers}

    subjects_by_code: dict[str, list[str]] = {code: [] for code, _kw in _DISCIPLINE_CODES}
    for subject_name in context.staffing.subject_names:
        code = _code_of_subject(subject_name)
        if code is not None:
            subjects_by_code[code].append(subject_name)

    def ids_for(names: tuple[str, ...]) -> set[int]:
        found: set[int] = set()
        for name in names:
            for cycle in (Cycle.FIRST, Cycle.SECOND):
                found |= context.staffing.by_subject_cycle.get((name, cycle), set())
        return found

    cells: list[str] = ["Effectif enseignant"]
    totals: dict[str, set[int]] = {"F": set(), "G": set()}
    for code, _keywords in _DISCIPLINE_CODES:
        ids = ids_for(tuple(subjects_by_code[code]))
        for genre in ("F", "G"):
            matching = {i for i in ids if gender_of.get(i) == genre}
            cells.append(str(len(matching)))
            totals[genre] |= matching
    cells.extend([str(len(totals["F"])), str(len(totals["G"]))])

    unknown = sum(1 for g in gender_of.values() if g not in ("F", "G"))
    note = "Un enseignant intervenant sur plusieurs disciplines est compté dans chacune."
    if unknown:
        note += f" {unknown} enseignant(s) sans sexe renseigné ne figurent dans aucune colonne."

    return ReportTable(
        number=21,
        title="Enseignants par discipline et par sexe",
        groups=groups,
        rows=(ReportRow(cells=tuple(cells)),) if context.staffing.subject_names else (),
        note=note,
        empty_message=(
            "Aucun emploi du temps saisi pour cette année : la répartition par discipline "
            f"ne peut pas être établie — {PENDING_NOTE.lower()}."
        ),
    )
