"""Regression tests: minute overlap and solver hard school blocks."""

from datetime import time
from types import SimpleNamespace

from app.services.schedule_event_service import blocked_indices
from app.utils.timetable_generator import Assignment, build_blocks, solve


def test_school_break_blocks_every_partially_overlapping_hour():
    blocks = build_blocks(["monday"], 8, 12, 60)
    events = [SimpleNamespace(day="monday", start_time=time(10, 10),
                              end_time=time(10, 25), class_id=None, blocks_courses=True)]
    assert blocked_indices(events, blocks, 1) == {2}


def test_class_specific_event_does_not_block_other_class():
    blocks = build_blocks(["monday"], 8, 12, 60)
    events = [SimpleNamespace(day="monday", start_time=time(10, 0),
                              end_time=time(10, 20), class_id=3, blocks_courses=True)]
    assert not blocked_indices(events, blocks, 2)


def test_generator_respects_school_break():
    blocks = build_blocks(["monday"], 8, 12, 60)
    result = solve([Assignment(teacher_id=4, subject_id=7, hours_per_week=2)], blocks, 60, school_blocked={1})
    assert result.feasible
    assert all(not (s.start_time < time(10, 0) and s.end_time > time(9, 0))
               for s in result.merged_slots)
