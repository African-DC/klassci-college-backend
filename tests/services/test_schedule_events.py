"""Regression tests for recurring non-teaching periods."""

from datetime import time
from types import SimpleNamespace

from app.services.schedule_event_service import blocked_indices
from app.utils.timetable_generator import Assignment, build_blocks, solve


def test_school_break_blocks_every_partially_overlapping_hour():
    blocks = build_blocks(["monday"], 8, 12, 60)
    events = [
        SimpleNamespace(
            day="monday",
            start_time=time(10, 10),
            end_time=time(10, 25),
            class_id=None,
            blocks_courses=True,
        )
    ]
    assert blocked_indices(events, blocks, 1) == {2}


def test_class_specific_event_does_not_block_other_class():
    blocks = build_blocks(["monday"], 8, 12, 60)
    events = [
        SimpleNamespace(
            day="monday",
            start_time=time(10, 0),
            end_time=time(10, 20),
            class_id=3,
            blocks_courses=True,
        )
    ]
    assert not blocked_indices(events, blocks, 2)


def test_generator_respects_school_break():
    blocks = build_blocks(["monday"], 8, 12, 60)
    result = solve(
        [Assignment(teacher_id=4, subject_id=7, hours_per_week=2)],
        blocks,
        60,
        school_blocked={1},
    )
    assert result.feasible
    assert all(
        not (slot.start_time < time(10, 0) and slot.end_time > time(9, 0))
        for slot in result.merged_slots
    )


def test_break_restarts_grid_without_losing_full_60_minute_session():
    blocks = build_blocks(
        ["monday"], 8, 13, 60, {"monday": [(600, 615)]}
    )
    assert [(b.start_minutes, b.end_minutes) for b in blocks] == [
        (480, 540), (540, 600),
        (615, 675), (675, 735), (735, 780),
    ]
    result = solve(
        [Assignment(teacher_id=4, subject_id=7, hours_per_week=3)],
        blocks, 60,
    )
    assert result.feasible
    assert sum(
        (slot.end_time.hour * 60 + slot.end_time.minute)
        - (slot.start_time.hour * 60 + slot.start_time.minute)
        for slot in result.merged_slots
    ) == 180
    assert all(
        slot.end_time <= time(10, 0) or slot.start_time >= time(10, 15)
        for slot in result.merged_slots
    )


def test_mid_hour_break_preserves_exact_minutes():
    blocks = build_blocks(
        ["monday"], 8, 14, 60, {"monday": [(610, 625)]}
    )
    assert (625, 685) in [
        (b.start_minutes, b.end_minutes) for b in blocks
    ]
    result = solve(
        [Assignment(teacher_id=5, subject_id=3, hours_per_week=4)],
        blocks, 60,
    )
    assert result.feasible
    assert sum(
        (slot.end_time.hour * 60 + slot.end_time.minute)
        - (slot.start_time.hour * 60 + slot.start_time.minute)
        for slot in result.merged_slots
    ) == 240
    assert all(
        slot.end_time <= time(10, 10) or slot.start_time >= time(10, 25)
        for slot in result.merged_slots
    )


def test_manual_lessons_are_subtracted_without_adding_duplicates():
    blocks = build_blocks(
        ["monday"], 8, 14, 60, {"monday": [(495, 585)]}
    )
    assert all(
        not (block.start_minutes < 585 and block.end_minutes > 495)
        for block in blocks
    )
    result = solve(
        [Assignment(teacher_id=5, subject_id=3, hours_per_week=3,
                    minutes_per_week=90)],
        blocks, 60,
    )
    assert result.feasible
    assert sum(
        (slot.end_time.hour * 60 + slot.end_time.minute)
        - (slot.start_time.hour * 60 + slot.start_time.minute)
        for slot in result.merged_slots
    ) == 90


def test_impossible_minute_capacity_never_silently_rounds_down():
    blocks = build_blocks(
        ["monday"], 8, 10, 60, {"monday": [(540, 570)]}
    )
    result = solve(
        [Assignment(teacher_id=5, subject_id=3, hours_per_week=2)],
        blocks, 60,
    )
    assert not result.feasible


def test_adjacent_breaks_merge_without_overlap_and_shift_after_pause():
    blocks = build_blocks(
        ["monday"], 8, 12, 60,
        {"monday": [(590, 605), (605, 620)]},
    )
    assert [(b.start_minutes, b.end_minutes) for b in blocks] == [
        (480, 540), (540, 590), (620, 680), (680, 720),
    ]


def test_excluded_event_only_affects_its_class():
    from app.services.schedule_event_service import to_blocked_periods

    events = [
        SimpleNamespace(
            day="monday", start_time=time(10, 0),
            end_time=time(10, 15), class_id=1, blocks_courses=True,
        ),
        SimpleNamespace(
            day="monday", start_time=time(12, 0),
            end_time=time(12, 15), class_id=None, blocks_courses=True,
        ),
        SimpleNamespace(
            day="monday", start_time=time(13, 0),
            end_time=time(13, 15), class_id=None, blocks_courses=False,
        ),
    ]
    assert to_blocked_periods(events, 2) == {"monday": [(720, 735)]}
