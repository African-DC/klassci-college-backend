"""Les filtres sélectionnent uniquement les données effectivement renseignées."""

from datetime import date

from app.services.class_roster_filters import (
    RosterFilters,
    describe_roster_filters,
    filter_roster_rows,
)

ROWS = [
    {
        "last_name": "KONE",
        "genre": "M",
        "birth_date": date(2012, 10, 14),
        "nationality": "Ivoirienne",
        "assignment_status": "affecte",
        "is_repeater": False,
        "is_new_student": True,
    },
    {
        "last_name": "YAO",
        "genre": "F",
        "birth_date": date(2011, 10, 15),
        "nationality": "Côte d'Ivoire",
        "assignment_status": "reaffecte",
        "is_repeater": True,
        "is_new_student": False,
    },
    {
        "last_name": "KEITA",
        "genre": "M",
        "birth_date": date(2010, 5, 1),
        "nationality": "Malienne",
        "assignment_status": "non_affecte",
        "is_repeater": None,
        "is_new_student": None,
    },
    {
        "last_name": "N'GUESSAN",
        "genre": None,
        "birth_date": None,
        "nationality": None,
        "assignment_status": None,
        "is_repeater": None,
        "is_new_student": None,
    },
]


def test_combined_filters_are_intersections():
    filters = RosterFilters(
        genre="M",
        age_min=14,
        age_max=16,
        nationalities=("Malienne",),
        assignment_statuses=("non_affecte",),
    )
    selected = filter_roster_rows(ROWS, filters, today=date(2026, 10, 14))
    assert [row["last_name"] for row in selected] == ["KEITA"]


def test_age_boundaries_and_missing_birth_dates():
    today = date(2026, 10, 14)
    older = filter_roster_rows(ROWS, RosterFilters(age_min=15), today=today)
    younger = filter_roster_rows(ROWS, RosterFilters(age_max=14), today=today)
    assert [row["last_name"] for row in older] == ["KEITA"]
    assert [row["last_name"] for row in younger] == ["KONE", "YAO"]


def test_multi_nationality_ignores_case_and_accents():
    filters = RosterFilters(nationalities=("cote d'ivoire", "MALIENNE"))
    selected = filter_roster_rows(ROWS, filters)
    assert [row["last_name"] for row in selected] == ["YAO", "KEITA"]


def test_assignment_and_nullable_flags_never_guess_unknown():
    filters = RosterFilters(assignment_statuses=("affecte", "reaffecte"))
    assert [row["last_name"] for row in filter_roster_rows(ROWS, filters)] == [
        "KONE",
        "YAO",
    ]
    assert [
        row["last_name"]
        for row in filter_roster_rows(ROWS, RosterFilters(is_repeater=False))
    ] == ["KONE"]
    assert [
        row["last_name"]
        for row in filter_roster_rows(ROWS, RosterFilters(is_new_student=False))
    ] == ["YAO"]


def test_unfiltered_roster_remains_unchanged_and_selection_is_printable():
    assert filter_roster_rows(ROWS) is ROWS
    assert "Garçons" in describe_roster_filters(RosterFilters(genre="M"))
