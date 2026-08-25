"""Chapitre III du rapport DEEP — ce que le sexe et le contrat des enseignants
font réellement sortir sur les tableaux 18, 19 et 21.

Ces tableaux partent à la DRENA. Les vérifier en cherchant des bouts de code
source ne prouve rien : c'est exactement ce qui a laissé passer une comparaison
à « G » là où la base stocke « M », et fait annoncer un corps enseignant
exclusivement féminin. On appelle donc les fonctions avec des enseignants
construits, et on lit les cellules produites.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.models.user import Genre, TeacherContract
from app.services.deep_report import chapter3_teachers as chapter
from app.services.deep_report._context import DisciplineStaffing, ReportContext
from app.services.deep_report._metrics import Cycle
from app.services.deep_report._types import MISSING, ReportTable

# ---------------------------------------------------------------------------
# Stand-ins
# ---------------------------------------------------------------------------


def _teacher(
    teacher_id: int,
    *,
    genre: str | None = None,
    contract: TeacherContract | None = None,
    cnps: str | None = None,
    authorization: str | None = None,
) -> SimpleNamespace:
    """Un enseignant tel que le contexte du rapport le rend."""
    return SimpleNamespace(
        id=teacher_id,
        first_name="Yao",
        last_name="Koffi",
        speciality="Mathématiques",
        genre=genre,
        contract_type=contract.value if contract else None,
        cnps_number=cnps,
        teaching_authorization_number=authorization,
    )


def _context(
    teachers: list[SimpleNamespace],
    *,
    staffing: DisciplineStaffing | None = None,
) -> ReportContext:
    context = ReportContext.__new__(ReportContext)
    object.__setattr__(context, "teachers", teachers)
    object.__setattr__(context, "staff", [])
    object.__setattr__(context, "staffing", staffing or DisciplineStaffing())
    return context


def _staffing_on_maths(*teacher_ids: int) -> DisciplineStaffing:
    """Un emploi du temps qui met les enseignants donnés sur les maths."""
    staffing = DisciplineStaffing()
    for teacher_id in teacher_ids:
        staffing.add("Mathématiques", Cycle.FIRST, teacher_id, class_name="6ème A")
    return staffing


def _row(table: ReportTable, label: str) -> tuple[str, ...]:
    for row in table.rows:
        if row.cells[0] == label:
            return row.cells
    raise AssertionError(f"Ligne « {label} » absente du tableau {table.number}")


# ---------------------------------------------------------------------------
# Le canevas de la DRENA
# ---------------------------------------------------------------------------


def test_les_trois_types_de_contrat_de_la_drena_existent() -> None:
    """Le canevas distingue permanents, vacataires et fonctionnaires."""
    assert {c.value for c in TeacherContract} == {"permanent", "vacataire", "fonctionnaire"}


def test_le_sexe_est_stocke_en_m_et_imprime_en_g() -> None:
    """Toute la confusion tient là : la colonne s'intitule « G », la donnée vaut
    « M ». Comparer la donnée au libellé ne trouve jamais personne."""
    assert {g.value for g in Genre} == {"M", "F"}
    assert chapter._sex_column(_teacher(1, genre=Genre.M.value)) == "G"
    assert chapter._sex_column(_teacher(2, genre=Genre.F.value)) == "F"
    assert chapter._sex_column(_teacher(3)) == MISSING


# ---------------------------------------------------------------------------
# Tableau 19 — synthèse par type de contrat
# ---------------------------------------------------------------------------


def test_un_enseignant_masculin_est_compte_en_colonne_g() -> None:
    """Le défaut d'origine : un homme entrait dans le total et dans aucune
    colonne, et le rapport annonçait un corps enseignant tout féminin."""
    context = _context(
        [
            _teacher(1, genre=Genre.M.value, contract=TeacherContract.PERMANENT),
            _teacher(2, genre=Genre.F.value, contract=TeacherContract.PERMANENT),
        ]
    )
    table = chapter._contract_table(context)
    # ("Permanents", 1F, 1G, 1T, 2F, 2G, 2T, F, G, T)
    assert _row(table, "Permanents")[-3:] == ("1", "1", "2")
    assert _row(table, "TOTAL")[-3:] == ("1", "1", "2")


def test_la_ventilation_par_cycle_compte_aussi_les_hommes() -> None:
    """Les colonnes de cycle souffraient du même test que le total."""
    context = _context(
        [_teacher(1, genre=Genre.M.value, contract=TeacherContract.FONCTIONNAIRE)],
        staffing=_staffing_on_maths(1),
    )
    cells = _row(chapter._contract_table(context), "Fonctionnaires")
    # 1er cycle : F=0, G=1, T=1 — l'emploi du temps ne porte que ce cycle.
    assert cells[1:4] == ("0", "1", "1")
    assert cells[4:7] == ("0", "0", "0")


def test_un_enseignant_sans_sexe_compte_au_total_pas_dans_la_ventilation() -> None:
    """Le ranger d'office en F ou G ferait dire au rapport une chose que
    personne n'a constatée ; l'oublier ferait mentir le total."""
    context = _context(
        [
            _teacher(1, contract=TeacherContract.VACATAIRE),
            _teacher(2, genre=Genre.F.value, contract=TeacherContract.VACATAIRE),
        ]
    )
    table = chapter._contract_table(context)
    assert _row(table, "Vacataires")[-3:] == ("1", "0", "2")
    assert table.note is not None
    assert "1 enseignant(s) sans sexe renseigné" in table.note


def test_un_enseignant_sans_contrat_est_annonce_absent_du_tableau() -> None:
    context = _context(
        [
            _teacher(1, genre=Genre.M.value, contract=TeacherContract.PERMANENT),
            _teacher(2, genre=Genre.M.value),
        ]
    )
    table = chapter._contract_table(context)
    assert _row(table, "TOTAL")[-1] == "1"
    assert table.note is not None
    assert "1 enseignant(s) sans type de contrat renseigné" in table.note


def test_le_tableau_19_sort_vierge_plutot_quen_grille_de_zeros() -> None:
    """Aucun contrat saisi : une grille de zéros déposée à la DRENA se lit
    « cet établissement n'a aucun permanent »."""
    table = chapter._contract_table(_context([_teacher(1, genre=Genre.F.value)]))
    assert table.rows == ()
    assert table.pending is True
    assert "type de contrat n'est renseigné pour aucun enseignant" in table.empty_message


def test_le_tableau_19_sans_aucun_enseignant_ne_parle_pas_de_contrat() -> None:
    """Zéro enseignant est un constat, pas une colonne manquante."""
    table = chapter._contract_table(_context([]))
    assert table.rows == ()
    assert table.empty_message == "Aucun enseignant enregistré."


# ---------------------------------------------------------------------------
# Tableau 21 — disciplines ventilées par sexe
# ---------------------------------------------------------------------------


def test_le_tableau_21_compte_les_enseignants_masculins() -> None:
    context = _context(
        [_teacher(1, genre=Genre.M.value), _teacher(2, genre=Genre.F.value)],
        staffing=_staffing_on_maths(1, 2),
    )
    table = chapter._discipline_by_gender_table(context)
    assert table.pending is False
    # Dernières cellules : TOTAL F puis TOTAL G.
    assert table.rows[0].cells[-2:] == ("1", "1")


def test_le_tableau_21_sort_vierge_quand_aucun_sexe_nest_saisi() -> None:
    context = _context([_teacher(1)], staffing=_staffing_on_maths(1))
    table = chapter._discipline_by_gender_table(context)
    assert table.rows == ()
    assert table.pending is True
    assert "sexe n'est renseigné pour aucun enseignant" in table.empty_message


def test_le_tableau_21_sans_emploi_du_temps_le_dit() -> None:
    table = chapter._discipline_by_gender_table(_context([_teacher(1, genre=Genre.F.value)]))
    assert table.rows == ()
    assert table.pending is True
    assert "Aucun emploi du temps saisi" in table.empty_message


# ---------------------------------------------------------------------------
# Tableau 18 — situation nominative
# ---------------------------------------------------------------------------


def test_le_tableau_18_imprime_le_sexe_et_le_contrat_reellement_saisis() -> None:
    """Les deux colonnes étaient figées sur « — » alors que la base les porte."""
    context = _context(
        [_teacher(1, genre=Genre.M.value, contract=TeacherContract.VACATAIRE)],
        staffing=_staffing_on_maths(1),
    )
    cells = chapter._teachers_table(context).rows[0].cells
    assert cells[2] == "G"
    assert cells[6] == "Vacataire"


def test_la_note_du_tableau_18_ne_nomme_que_les_colonnes_vides() -> None:
    """Annoncer « à compléter » une colonne que l'école vient de saisir ferait
    douter le lecteur du reste du document."""
    renseigne = _context(
        [
            _teacher(
                1,
                genre=Genre.F.value,
                contract=TeacherContract.PERMANENT,
                cnps="CI-123",
                authorization="AUT-9",
            )
        ]
    )
    note = chapter._teachers_table(renseigne).note or ""
    assert "« Sexe »" not in note
    assert "« N° CNPS »" not in note
    assert "« Diplôme »" in note

    vide = _context([_teacher(1)])
    note_vide = chapter._teachers_table(vide).note or ""
    assert "« Sexe »" in note_vide
    assert "« N° CNPS »" in note_vide


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------


def test_les_quatre_tableaux_se_construisent_reellement() -> None:
    """Vérifier une signature ne prouve rien : c'est en appelant qu'on voit
    qu'un appelant n'a pas suivi."""
    tables = chapter.build_tables(_context([]))
    assert [t.number for t in tables] == [18, 19, 20, 21]


def test_un_etablissement_sans_aucune_saisie_ne_signe_aucun_zero() -> None:
    """Le contrat du module : ce qu'on ne sait pas s'écrit « à compléter »."""
    tables = {t.number: t for t in chapter.build_tables(_context([_teacher(1), _teacher(2)]))}
    assert tables[19].pending is True
    assert tables[21].pending is True
    assert tables[19].rows == ()
    assert tables[21].rows == ()
