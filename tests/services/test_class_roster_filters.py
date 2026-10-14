from datetime import date

import pytest
from pydantic import ValidationError

from app.services.class_roster_filters import RosterFilters, filter_roster


def test_combined_filters_exclude_unmatched_and_unknown():
    students = [
        {
            "genre": "M",
            "birth_date": date(2012, 10, 14),
            "nationality": "Ivoirienne",
            "assignment_status": "affecte",
            "is_repeater": False,
        },
        {
            "genre": "F",
            "birth_date": date(2011, 8, 1),
            "nationality": "Malienne",
            "assignment_status": "non_affecte",
            "is_repeater": True,
        },
        {
            "genre": "M",
            "birth_date": None,
            "nationality": "Ivoirienne",
            "assignment_status": "affecte",
            "is_repeater": False,
        },
    ]
    filters = RosterFilters(
        genre="M",
        age_min=14,
        age_max=14,
        nationalities=["ivoirienne", "Malienne"],
        assignments=["affecte"],
        repeaters=False,
    )
    assert filter_roster(students, filters, today=date(2026, 10, 14)) == students[:1]


def test_multiple_assignment_selections():
    students = [
        {"assignment_status": "affecte"},
        {"assignment_status": "reaffecte"},
        {"assignment_status": "non_affecte"},
    ]
    assert len(filter_roster(students, RosterFilters(assignments=["affecte", "reaffecte"]))) == 2


def test_invalid_age_range():
    with pytest.raises(ValidationError):
        RosterFilters(age_min=18, age_max=12)


def test_empty_filters_leave_valid_roster_unchanged():
    students = [{"genre": "M"}, {"genre": "F"}, {"genre": None}]
    assert filter_roster(students, RosterFilters()) == students
