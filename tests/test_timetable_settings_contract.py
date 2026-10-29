"""Timetable settings must be validated before tenant mutation."""

import pytest
from pydantic import ValidationError

from app.schemas.admin import TimetableSettingsUpdate


def test_valid_school_timetable_rules():
    rules = TimetableSettingsUpdate(
        day_start_hour=8, day_end_hour=16, slot_duration_minutes=55
    )
    assert rules.slot_duration_minutes == 55


@pytest.mark.parametrize(
    "data",
    [
        {"day_start_hour": 18, "day_end_hour": 8, "slot_duration_minutes": 60},
        {"day_start_hour": 8, "day_end_hour": 8, "slot_duration_minutes": 60},
        {"day_start_hour": 8, "day_end_hour": 19, "slot_duration_minutes": 0},
    ],
)
def test_invalid_school_timetable_rules(data):
    with pytest.raises(ValidationError):
        TimetableSettingsUpdate(**data)
