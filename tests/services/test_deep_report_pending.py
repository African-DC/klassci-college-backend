"""Les tableaux du rapport DEEP que la plateforme ne sait pas encore remplir.

Quatre entités du canevas — visites de classe, formations, transferts et
bourses — existent en base sans aucun écran de saisie. Leurs tableaux sortent
donc systématiquement vides. Un tableau vide sans mention se lit à la DRENA
comme un constat : « cet établissement n'a aucun boursier », « aucune visite
de classe ce trimestre ». Ces tests vérifient que la mention d'attente est
bien posée, et qu'elle disparaît dès qu'une donnée existe.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services.deep_report import chapter1_pedagogy, chapter2_movements, chapter3_admin
from app.services.deep_report._context import ReportContext

_SIXIEME = SimpleNamespace(id=1, name="6ème", order=1)
_SIXIEME_A = SimpleNamespace(id=11, name="6ème A", level=_SIXIEME)


def _context(
    *,
    visits: list[object] | None = None,
    trainings: list[object] | None = None,
    scholarships: list[object] | None = None,
    staff: list[object] | None = None,
) -> ReportContext:
    return ReportContext(
        academic_year=SimpleNamespace(id=1, name="2025-2026"),
        trimester=1,
        lines=[],
        levels=[_SIXIEME],
        teachers=[],
        staff=staff or [],
        visits=visits or [],
        trainings=trainings or [],
        transfers=[],
        scholarships=scholarships or [],
        staffing=SimpleNamespace(
            by_subject_cycle={},
            classes_by_teacher={},
            subjects_by_teacher={},
            subject_names=set(),
        ),
        has_history=True,
    )


def _teacher() -> SimpleNamespace:
    return SimpleNamespace(id=1, first_name="Yao", last_name="Koffi", speciality="Maths")


# ---------------------------------------------------------------------------
# Tableaux 1 et 2 — visites de classe et formations
# ---------------------------------------------------------------------------


def test_les_visites_de_classe_non_saisies_portent_la_mention_dattente() -> None:
    tables = {t.number: t for t in chapter1_pedagogy.build(_context()).tables}
    assert tables[1].rows == ()
    assert tables[1].pending is True
    assert "à compléter manuellement" in tables[1].empty_message


def test_une_visite_enregistree_retire_la_mention_dattente() -> None:
    """Le jour où l'écran de saisie existe, le tableau doit cesser de dire
    « à compléter » sans qu'on y retouche."""
    visit = SimpleNamespace(
        teacher=_teacher(),
        subject=SimpleNamespace(name="Mathématiques"),
        visit_date=date(2026, 1, 15),
        observations="Séance conforme",
    )
    tables = {t.number: t for t in chapter1_pedagogy.build(_context(visits=[visit])).tables}
    assert tables[1].pending is False
    assert len(tables[1].rows) == 1


def test_les_formations_non_saisies_portent_la_mention_dattente() -> None:
    tables = {t.number: t for t in chapter1_pedagogy.build(_context()).tables}
    assert tables[2].rows == ()
    assert tables[2].pending is True


def test_une_formation_enregistree_retire_la_mention_dattente() -> None:
    training = SimpleNamespace(
        teacher=_teacher(),
        subject=SimpleNamespace(name="Mathématiques"),
        discipline_label="Mathématiques",
        training_date=date(2026, 2, 3),
        title="Séminaire DRENA",
        observations=None,
    )
    tables = {t.number: t for t in chapter1_pedagogy.build(_context(trainings=[training])).tables}
    assert tables[2].pending is False


# ---------------------------------------------------------------------------
# Tableau 13 — boursiers
# ---------------------------------------------------------------------------


def test_aucune_bourse_saisie_nest_pas_aucun_boursier() -> None:
    """Sans écran de saisie, « aucune ligne » ne prouve rien : la mention
    d'attente empêche l'inspection de lire un constat."""
    table = chapter2_movements.scholarships_table(_context())
    assert table.rows == ()
    assert table.pending is True
    assert "à compléter manuellement" in table.empty_message


# ---------------------------------------------------------------------------
# Tableau 22 — personnel administratif
# ---------------------------------------------------------------------------


def _staff(*, cnps: str | None = None, authorization: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        first_name="Sophie",
        last_name="Yao",
        position="Secrétaire",
        phone="0700000000",
        cnps_number=cnps,
        teaching_authorization_number=authorization,
    )


def test_le_tableau_22_annonce_les_numeros_administratifs_manquants() -> None:
    """Les deux colonnes sortent « — » faute d'écran de saisie : le dire évite
    que l'inspection les croie volontairement vides."""
    tables = {t.number: t for t in chapter3_admin.build_tables(_context(staff=[_staff()]))}
    note = tables[22].note or ""
    assert "« N° CNPS »" in note
    assert "« N° autorisation d'enseigner »" in note


def test_le_tableau_22_se_tait_quand_les_numeros_sont_saisis() -> None:
    staff = [_staff(cnps="CI-4471", authorization="AUT-88")]
    tables = {t.number: t for t in chapter3_admin.build_tables(_context(staff=staff))}
    assert tables[22].note is None
    assert tables[22].rows[0].cells[3] == "CI-4471"
