"""Totaux du rapport DEEP : par classe, par niveau, par cycle.

Le canevas empile trois niveaux d'agrégation. Une erreur de regroupement y est
invisible à la lecture — les lignes ont l'air justes une par une — mais
l'inspection additionne, et les totaux doivent tomber.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.deep_report import (
    chapter1_recaps,
    chapter2_gender,
    chapter2_movements,
    chapter2_pyramids,
)
from app.services.deep_report._context import ReportContext, StudentLine
from app.services.deep_report._metrics import cycle_of_level
from app.services.deep_report._types import MISSING

_SIXIEME = SimpleNamespace(id=1, name="6ème", order=1)
_TERMINALE = SimpleNamespace(id=2, name="Terminale", order=7)

_SIXIEME_A = SimpleNamespace(id=11, name="6ème A", level=_SIXIEME)
_SIXIEME_B = SimpleNamespace(id=12, name="6ème B", level=_SIXIEME)
_TLE_D = SimpleNamespace(id=21, name="Terminale D", level=_TERMINALE)


def _line(
    student_id: int,
    class_,
    *,
    genre: str | None = "F",
    average: str | None = None,
    assignment: str | None = "affecte",
    decision: str | None = None,
    birth_year: int | None = 2010,
) -> StudentLine:
    """Un élève inscrit, réduit à ce que les tableaux lisent de lui."""
    birth_date = SimpleNamespace(year=birth_year) if birth_year else None
    student = SimpleNamespace(
        id=student_id,
        first_name=f"Prenom{student_id}",
        last_name=f"Nom{student_id}",
        genre=genre,
        birth_date=birth_date,
        enrollment_number=f"MAT{student_id}",
        previous_school=None,
        transfer_decision_number=None,
    )
    enrollment = SimpleNamespace(
        id=student_id * 100,
        assignment_status=assignment,
        assignment_decision_number=None,
        notes=None,
    )
    bulletin = (
        SimpleNamespace(
            average=Decimal(average),
            rank=1,
            council_decision=decision,
        )
        if average is not None
        else None
    )
    return StudentLine(
        enrollment=enrollment,
        student=student,
        class_=class_,
        level=class_.level,
        cycle=cycle_of_level(class_.level.name, class_.level.order),
        bulletin=bulletin,
        is_repeater=False,
    )


def _context(lines: list[StudentLine]) -> ReportContext:
    return ReportContext(
        academic_year=SimpleNamespace(id=1, name="2025-2026"),
        trimester=1,
        lines=lines,
        levels=[_SIXIEME, _TERMINALE],
        teachers=[],
        staff=[],
        visits=[],
        trainings=[],
        transfers=[],
        scholarships=[],
        staffing=SimpleNamespace(
            by_subject_cycle={},
            classes_by_teacher={},
            subjects_by_teacher={},
            subject_names=set(),
        ),
        has_history=True,
    )


def _row_by_label(table, label: str):
    for row in table.rows:
        if row.cells[0] == label:
            return row
    raise AssertionError(f"Ligne « {label} » absente du tableau {table.number}")


# ---------------------------------------------------------------------------
# Tableaux 5 à 7 — récapitulatifs par classe et par niveau
# ---------------------------------------------------------------------------


def _recap_population() -> list[StudentLine]:
    return [
        _line(1, _SIXIEME_A, genre="F", average="15.00"),
        _line(2, _SIXIEME_A, genre="M", average="10.00"),  # borne haute → réussite
        _line(3, _SIXIEME_A, genre="F", average="8.50"),  # borne basse → intermédiaire
        _line(4, _SIXIEME_B, genre="M", average="8.49"),  # juste sous → échec
        _line(5, _SIXIEME_B, genre="F", average=None),  # non classé
        _line(6, _TLE_D, genre="M", average="12.00"),
    ]


def test_total_de_niveau_somme_ses_classes():
    tables = chapter1_recaps.build_tables(_context(_recap_population()))
    everyone = next(table for table in tables if table.number == 7)

    sixieme = _row_by_label(everyone, "EFF. TOTAL — 6ème")
    # Effectifs réels F / G / T puis effectifs classés F / G / T
    assert sixieme.cells[1:4] == ("3", "2", "5")
    assert sixieme.cells[4:7] == ("2", "2", "4")
    assert sixieme.emphasis is True


def test_seuils_de_moyenne_dans_le_recapitulatif_de_niveau():
    tables = chapter1_recaps.build_tables(_context(_recap_population()))
    everyone = next(table for table in tables if table.number == 7)
    sixieme = _row_by_label(everyone, "EFF. TOTAL — 6ème")

    # 15,00 et 10,00 réussissent ; 8,50 est intermédiaire ; 8,49 échoue.
    assert sixieme.cells[7] == "2"
    assert sixieme.cells[9] == "1"
    assert sixieme.cells[11] == "1"


def test_pourcentages_calcules_sur_les_classes_pas_sur_les_inscrits():
    """Cinq inscrits, quatre classés : 50 % de réussite, pas 40 %."""
    tables = chapter1_recaps.build_tables(_context(_recap_population()))
    everyone = next(table for table in tables if table.number == 7)
    sixieme = _row_by_label(everyone, "EFF. TOTAL — 6ème")
    assert sixieme.cells[8] == "50,0 %"


def test_total_etablissement_somme_tous_les_niveaux():
    tables = chapter1_recaps.build_tables(_context(_recap_population()))
    everyone = next(table for table in tables if table.number == 7)
    total = _row_by_label(everyone, "TOTAL ÉTABLISSEMENT")
    assert total.cells[3] == "6"
    assert total.cells[6] == "5"


def test_classe_sans_eleve_classe_affiche_un_tiret_pas_zero_pour_cent():
    lines = [_line(1, _SIXIEME_A, average=None)]
    tables = chapter1_recaps.build_tables(_context(lines))
    everyone = next(table for table in tables if table.number == 7)
    row = _row_by_label(everyone, "6ème A")
    assert row.cells[8] == MISSING


def test_recapitulatif_affectes_ecarte_les_non_affectes():
    lines = [
        _line(1, _SIXIEME_A, assignment="affecte", average="12.00"),
        _line(2, _SIXIEME_A, assignment="reaffecte", average="12.00"),
        _line(3, _SIXIEME_A, assignment="non_affecte", average="12.00"),
    ]
    tables = chapter1_recaps.build_tables(_context(lines))
    subsidised = next(table for table in tables if table.number == 5)
    unsubsidised = next(table for table in tables if table.number == 6)

    assert _row_by_label(subsidised, "6ème A").cells[3] == "2"
    assert _row_by_label(unsubsidised, "6ème A").cells[3] == "1"


def test_inscriptions_sans_statut_sont_signalees_et_non_reparties():
    lines = [
        _line(1, _SIXIEME_A, assignment=None, average="12.00"),
        _line(2, _SIXIEME_A, assignment="affecte", average="12.00"),
    ]
    tables = chapter1_recaps.build_tables(_context(lines))
    subsidised = next(table for table in tables if table.number == 5)
    everyone = next(table for table in tables if table.number == 7)

    assert _row_by_label(subsidised, "6ème A").cells[3] == "1"
    assert _row_by_label(everyone, "6ème A").cells[3] == "2"
    assert "sans statut d'affectation" in (subsidised.note or "")


# ---------------------------------------------------------------------------
# Tableau 9 — transferts et réintégrations
# ---------------------------------------------------------------------------


def test_transfert_deduit_de_la_fiche_eleve_quand_rien_n_est_enregistre():
    """Le secrétariat a saisi l'école d'origine : le tableau ne doit pas rester vide."""
    line = _line(1, _SIXIEME_A)
    line.student.previous_school = "Collège Moderne de Bouaké"
    line.student.transfer_decision_number = "TR-2025-12"
    table = chapter2_movements.transfers_table(_context([line]))

    assert len(table.rows) == 1
    assert table.rows[0].cells[2] == "Collège Moderne de Bouaké"
    assert "fiche élève" in table.rows[0].cells[5]
    assert "déduite" in (table.note or "")


def test_mouvement_enregistre_prime_sur_la_fiche_eleve():
    line = _line(1, _SIXIEME_A)
    line.student.previous_school = "Collège Moderne de Bouaké"
    context = _context([line])
    context.transfers = [
        (
            SimpleNamespace(
                kind="reintegration",
                origin_school="Lycée municipal",
                decision_number="RE-2025-03",
            ),
            line,
        )
    ]
    table = chapter2_movements.transfers_table(context)

    assert len(table.rows) == 1
    assert table.rows[0].cells[2] == "Lycée municipal"
    assert table.rows[0].cells[5] == "Réintégration"
    assert table.note is None


def test_numerotation_continue_des_deux_sources():
    first = _line(1, _SIXIEME_A)
    second = _line(2, _SIXIEME_B)
    second.student.previous_school = "Collège Moderne de Bouaké"
    context = _context([first, second])
    context.transfers = [
        (
            SimpleNamespace(
                kind="transfert", origin_school="Lycée municipal", decision_number=None
            ),
            first,
        )
    ]
    table = chapter2_movements.transfers_table(context)

    assert [row.cells[0] for row in table.rows] == ["1", "2"]


# ---------------------------------------------------------------------------
# Tableau 10 — totaux par cycle
# ---------------------------------------------------------------------------


def test_totaux_par_cycle_du_conseil_de_classe():
    lines = [
        _line(1, _SIXIEME_A, genre="F", average="12.00", decision="passage"),
        _line(2, _SIXIEME_B, genre="M", average="9.00", decision="redoublement"),
        _line(3, _TLE_D, genre="F", average="14.00", decision="passage"),
    ]
    table = chapter2_movements.council_table(_context(lines))

    first_cycle = _row_by_label(table, "Total 1er cycle")
    second_cycle = _row_by_label(table, "Total 2nd cycle")
    overall = _row_by_label(table, "TOTAL GÉNÉRAL")

    assert first_cycle.cells[1:4] == ("1", "1", "2")
    assert second_cycle.cells[1:4] == ("1", "0", "1")
    assert overall.cells[1:4] == ("2", "1", "3")


def test_eleve_sans_decision_reste_en_colonne_dediee():
    lines = [_line(1, _SIXIEME_A, average="12.00", decision=None)]
    table = chapter2_movements.council_table(_context(lines))
    overall = _row_by_label(table, "TOTAL GÉNÉRAL")

    # Quatre décisions × 3 colonnes après l'effectif, puis « Sans décision ».
    assert overall.cells[-3:] == ("1", "0", "1")
    assert "sans décision de conseil" in (table.note or "")


# ---------------------------------------------------------------------------
# Tableaux 14 à 17 — lectures par sexe
# ---------------------------------------------------------------------------


def test_synthese_genre_par_cycle():
    lines = [
        _line(1, _SIXIEME_A, genre="F", average="12.00"),
        _line(2, _SIXIEME_B, genre="M", average="12.00"),
        _line(3, _TLE_D, genre="F", average="12.00"),
        _line(4, _TLE_D, genre=None, average="12.00"),
    ]
    tables = chapter2_gender.build_tables(_context(lines))
    synthesis = next(table for table in tables if table.number == 15)

    assert _row_by_label(synthesis, "F").cells[1:] == ("1", "1", "2")
    assert _row_by_label(synthesis, "G").cells[1:] == ("1", "0", "1")
    assert _row_by_label(synthesis, "Non renseigné").cells[1:] == ("0", "1", "1")
    assert _row_by_label(synthesis, "Total").cells[1:] == ("2", "2", "4")


def test_recapitulatif_par_sexe_isole_les_non_classes():
    lines = [
        _line(1, _SIXIEME_A, genre="F", average="12.00"),
        _line(2, _SIXIEME_A, genre="M", average=None),
    ]
    tables = chapter2_gender.build_tables(_context(lines))
    overall = next(table for table in tables if table.number == 14)
    row = _row_by_label(overall, "6ème")

    assert row.cells[1:4] == ("1", "1", "2")  # effectifs réels
    assert row.cells[4:7] == ("1", "0", "1")  # effectifs classés
    assert row.cells[-3:] == ("0", "1", "1")  # non classés


# ---------------------------------------------------------------------------
# Tableaux 11 et 12 — pyramides
# ---------------------------------------------------------------------------


def test_base_de_pyramide_par_niveau_et_total():
    lines = [
        _line(1, _SIXIEME_A, genre="F"),
        _line(2, _SIXIEME_B, genre="M"),
        _line(3, _TLE_D, genre="F"),
    ]
    table = chapter2_pyramids.pyramid_table(_context(lines))
    base = _row_by_label(table, "BASE")
    # 6ème (F, G), Terminale (F, G), puis le total (F, G)
    assert base.cells[1:] == ("1", "1", "1", "0", "2", "1")


def test_annee_de_naissance_inconnue_reste_a_part():
    lines = [
        _line(1, _SIXIEME_A, genre="F", birth_year=2010),
        _line(2, _SIXIEME_A, genre="M", birth_year=None),
    ]
    table = chapter2_pyramids.birth_year_table(_context(lines))
    labels = [row.cells[0] for row in table.rows]
    assert "Non renseignée" in labels
    assert labels[-1] == "Non renseignée"
    assert "sans date de naissance" in (table.note or "")
