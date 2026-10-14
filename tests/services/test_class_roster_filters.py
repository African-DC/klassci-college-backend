"""Le même filtre porte sur l'effectif validé pour les trois exports."""

from datetime import date

from app.services.class_roster_filters import RosterFilters, describe_roster_filters, filter_roster_rows


ROWS = [
    {"last_name": "KONE", "genre": "M", "birth_date": date(2012, 10, 14), "nationality": "Ivoirienne", "assignment_status": "affecte", "is_repeater": False, "is_new_student": True},
    {"last_name": "YAO", "genre": "F", "birth_date": date(2011, 10, 15), "nationality": "Côte d'Ivoire", "assignment_status": "reaffecte", "is_repeater": True, "is_new_student": False},
    {"last_name": "KEITA", "genre": "M", "birth_date": date(2010, 5, 1), "nationality": "Malienne", "assignment_status": "non_affecte", "is_repeater": None, "is_new_student": None},
    {"last_name": "N'GUESSAN", "genre": None, "birth_date": None, "nationality": None, "assignment_status": None, "is_repeater": None, "is_new_student": None},
]


def test_combined_filters_are_intersections():
    filters = RosterFilters(
        genre="M", age_min=14, age_max=16,
        nationalities=("Malienne",), assignment_statuses=("non_affecte",),
    )
    assert [r["last_name"] for r in filter_roster_rows(ROWS, filters, today=date(2026, 10, 14))] == ["KEITA"]


def test_age_boundaries_and_missing_birth_dates():
    today = date(2026, 10, 14)
    assert [r["last_name"] for r in filter_roster_rows(ROWS, RosterFilters(age_min=14), today=today)] == ["KONE", "KEITA"]
    assert [r["last_name"] for r in filter_roster_rows(ROWS, RosterFilters(age_max=13), today=today)] == ["YAO"]


def test_multi_nationality_ignores_case_and_accents():
    filters = RosterFilters(nationalities=("cote d'ivoire", "MALIENNE"))
    assert [r["last_name"] for r in filter_roster_rows(ROWS, filters)] == ["YAO", "KEITA"]


def test_assignment_and_nullable_flags_never_guess_unknown():
    assert [r["last_name"] for r in filter_roster_rows(ROWS, RosterFilters(assignment_statuses=("affecte", "reaffecte")))] == ["KONE", "YAO"]
    assert [r["last_name"] for r in filter_roster_rows(ROWS, RosterFilters(is_repeater=False))] == ["KONE"]
    assert [r["last_name"] for r in filter_roster_rows(ROWS, RosterFilters(is_new_student=False))] == ["YAO"]


def test_unfiltered_roster_remains_unchanged_and_selection_is_printable():
    assert filter_roster_rows(ROWS) is ROWS
    assert "Garçons" in describe_roster_filters(RosterFilters(genre="M"))
