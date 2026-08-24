"""Chapitre III — personnel enseignant : tableaux 18 à 21.

KLASSCI connaît l'identité, la discipline et le service de chaque enseignant.
Le sexe, le type de contrat et les deux numéros administratifs existent en
base mais n'ont pas encore d'écran de saisie : tant qu'aucun enseignant ne les
porte, la colonne sort « — » et le tableau qui repose entièrement dessus est
livré vierge avec sa mention d'attente, plutôt qu'en grille de zéros. Un zéro
déposé à la DRENA se lit comme un constat.

Le canevas intitule « G » la colonne des garçons, quand la valeur stockée vaut
« M ». La traduction se fait à l'affichage, via `_format.sex`, jamais au moment
de comparer une donnée.
"""

from __future__ import annotations

from app.models.user import Genre, TeacherContract, TeacherProfile
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

# Colonnes du canevas que KLASSCI ne stocke nulle part : elles sortent vides
# quoi qu'il arrive, et le chef d'établissement les porte à la main.
_UNCOLLECTED_COLUMNS: tuple[str, ...] = (
    "Date et lieu de naissance",
    "Diplôme",
    "Date de prise de service",
    "Observations",
)

# Colonnes qui existent en base mais n'ont pas encore d'écran de saisie : on ne
# les annonce comme à compléter que si aucun enseignant ne les porte, pour que
# la note cesse d'elle-même de mentir le jour où l'école les renseigne.
_UNFILLED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("Sexe", "genre"),
    ("Type de contrat", "contract_type"),
    ("N° CNPS", "cnps_number"),
    ("N° autorisation d'enseigner", "teaching_authorization_number"),
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


_CONTRACT_LABELS: dict[TeacherContract, str] = {
    TeacherContract.PERMANENT: "Permanents",
    TeacherContract.VACATAIRE: "Vacataires",
    TeacherContract.FONCTIONNAIRE: "Fonctionnaires",
}


def _field(teacher: TeacherProfile, name: str) -> str:
    """Valeur texte d'une colonne administrative, vide si non renseignée."""
    raw = getattr(teacher, name, None)
    return str(getattr(raw, "value", raw) or "").strip()


def _is_female(teacher: TeacherProfile) -> bool | None:
    """« Est une femme », ou None si le sexe n'est pas renseigné.

    On compare à `Genre.M` / `Genre.F`, les seules valeurs que la base
    contient. Le libellé « G » du canevas est une affaire d'affichage :
    comparer la donnée à « G » ne trouve jamais personne, et sortait un corps
    enseignant exclusivement féminin sur les tableaux 19 et 21.
    """
    genre = _field(teacher, "genre").upper()
    if genre == Genre.F.value:
        return True
    if genre == Genre.M.value:
        return False
    return None


def _sex_column(teacher: TeacherProfile) -> str:
    """Colonne « F » ou « G » du canevas, « — » si le sexe manque."""
    return fmt.sex(_is_female(teacher))


def _contract_of(teacher: TeacherProfile) -> str:
    """Valeur brute du type de contrat, vide si non renseigné."""
    return _field(teacher, "contract_type")


def build_tables(context: ReportContext) -> tuple[ReportTable, ...]:
    """Tableaux 18 à 21."""
    return (
        _teachers_table(context),
        _contract_table(context),
        _discipline_table(context),
        _discipline_by_gender_table(context),
    )


def _teachers_note(context: ReportContext) -> str:
    """Avertissement du tableau 18, calculé sur ce qui manque réellement.

    Annoncer « non collecté » une colonne que l'école vient de renseigner
    ferait douter le lecteur du reste du document : la note ne nomme que les
    colonnes effectivement vides.
    """
    labels = list(_UNCOLLECTED_COLUMNS)
    labels.extend(
        label
        for label, attribute in _UNFILLED_COLUMNS
        if not any(_field(teacher, attribute) for teacher in context.teachers)
    )
    columns = ", ".join(f"« {label} »" for label in sorted(labels))
    return f"Colonnes {columns} : non renseignées — {PENDING_NOTE.lower()}."


def _teachers_table(context: ReportContext) -> ReportTable:
    """Tableau 18 — situation nominative des enseignants."""
    rows: list[ReportRow] = []
    for index, teacher in enumerate(context.teachers, start=1):
        subjects = sorted(context.staffing.subjects_by_teacher.get(teacher.id, set()))
        classes = sorted(context.staffing.classes_by_teacher.get(teacher.id, set()))
        contract = _contract_of(teacher)
        rows.append(
            ReportRow(
                cells=(
                    str(index),
                    f"{teacher.last_name} {teacher.first_name}".strip(),
                    _sex_column(teacher),
                    MISSING,  # Date et lieu de naissance — non collectés
                    MISSING,  # Diplôme — non collecté
                    fmt.text(", ".join(subjects) or teacher.speciality),
                    fmt.text(contract.capitalize() if contract else None),
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
        note=_teachers_note(context),
        empty_message="Aucun enseignant enregistré.",
    )


def _contract_table(context: ReportContext) -> ReportTable:
    """Tableau 19 — synthèse par type de contrat, ventilée par cycle et par sexe.

    Tant qu'aucun enseignant ne porte de type de contrat, la grille n'est pas
    produite : elle sortirait en zéros, et un zéro déposé à la DRENA se lit
    « cet établissement n'a aucun permanent », pas « cette colonne n'a pas été
    saisie ». Dès qu'un contrat est renseigné, le tableau se calcule ; un
    enseignant dont le contrat ou le sexe manque est compté dans le total mais
    dans aucune colonne ventilée, et la note le dit.
    """

    def cycles_of(teacher_id: int) -> set[Cycle]:
        return {
            cycle
            for (_name, cycle), ids in context.staffing.by_subject_cycle.items()
            if teacher_id in ids
        }

    rows: list[ReportRow] = []
    totals = {"1F": 0, "1G": 0, "1T": 0, "2F": 0, "2G": 0, "2T": 0, "F": 0, "G": 0, "T": 0}
    known_contracts = any(_contract_of(teacher) for teacher in context.teachers)

    if known_contracts:
        for contract, label in _CONTRACT_LABELS.items():
            counts = dict.fromkeys(totals, 0)
            for teacher in context.teachers:
                if _contract_of(teacher) != contract.value:
                    continue
                # « G » est le libellé du canevas ; la donnée, elle, vaut « M ».
                column = _sex_column(teacher)
                cycles = cycles_of(teacher.id)
                counts["T"] += 1
                if column in ("F", "G"):
                    counts[column] += 1
                for cycle, prefix in ((Cycle.FIRST, "1"), (Cycle.SECOND, "2")):
                    if cycle in cycles:
                        counts[f"{prefix}T"] += 1
                        if column in ("F", "G"):
                            counts[f"{prefix}{column}"] += 1
            for key in totals:
                totals[key] += counts[key]
            rows.append(
                ReportRow(
                    cells=(
                        label,
                        *(
                            str(counts[k])
                            for k in ("1F", "1G", "1T", "2F", "2G", "2T", "F", "G", "T")
                        ),
                    )
                )
            )
        rows.append(
            ReportRow(
                cells=(
                    "TOTAL",
                    *(str(totals[k]) for k in ("1F", "1G", "1T", "2F", "2G", "2T", "F", "G", "T")),
                ),
                emphasis=True,
            )
        )

    unknown_contract = sum(1 for t in context.teachers if not _contract_of(t))
    unknown_sex = sum(1 for t in context.teachers if _is_female(t) is None)

    notes: list[str] = []
    if rows and unknown_contract:
        notes.append(
            f"{unknown_contract} enseignant(s) sans type de contrat renseigné : "
            "absents de ce tableau."
        )
    if rows and unknown_sex:
        notes.append(
            f"{unknown_sex} enseignant(s) sans sexe renseigné : comptés dans les totaux, "
            "dans aucune colonne F ou G."
        )

    if not context.teachers:
        empty_message = "Aucun enseignant enregistré."
    else:
        empty_message = (
            "Le type de contrat n'est renseigné pour aucun enseignant : la synthèse ne "
            f"peut pas être établie — {PENDING_NOTE.lower()}."
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
        note=" ".join(notes) if notes else None,
        pending=not rows,
        empty_message=empty_message,
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
    """Tableau 21 — même grille que le 20, ventilée par sexe.

    Deux conditions pour qu'il veuille dire quelque chose : un emploi du temps
    saisi, et au moins un enseignant dont le sexe est renseigné. À défaut, la
    grille sort vierge avec sa mention d'attente plutôt qu'en zéros.
    """
    groups = (
        HeaderGroup("Établissement"),
        *(
            HeaderGroup(code, subs=("F", "G"), align="center")
            for code, _keywords in _DISCIPLINE_CODES
        ),
        HeaderGroup("TOTAL", subs=("F", "G"), align="center"),
    )

    # Clé « F » / « G » du canevas par enseignant, traduite une seule fois.
    column_of = {teacher.id: _sex_column(teacher) for teacher in context.teachers}
    known_sex = any(column in ("F", "G") for column in column_of.values())

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
        for column in ("F", "G"):
            matching = {i for i in ids if column_of.get(i) == column}
            cells.append(str(len(matching)))
            totals[column] |= matching
    cells.extend([str(len(totals["F"])), str(len(totals["G"]))])

    produced = bool(context.staffing.subject_names) and known_sex
    unknown = sum(1 for column in column_of.values() if column not in ("F", "G"))
    note = None
    if produced:
        note = "Un enseignant intervenant sur plusieurs disciplines est compté dans chacune."
        if unknown:
            note += f" {unknown} enseignant(s) sans sexe renseigné ne figurent dans aucune colonne."

    if not context.staffing.subject_names:
        empty_message = (
            "Aucun emploi du temps saisi pour cette année : la répartition par discipline "
            f"ne peut pas être établie — {PENDING_NOTE.lower()}."
        )
    else:
        empty_message = (
            "Le sexe n'est renseigné pour aucun enseignant : la ventilation par sexe ne "
            f"peut pas être établie — {PENDING_NOTE.lower()}."
        )

    return ReportTable(
        number=21,
        title="Enseignants par discipline et par sexe",
        groups=groups,
        rows=(ReportRow(cells=tuple(cells)),) if produced else (),
        note=note,
        pending=not produced,
        empty_message=empty_message,
    )
