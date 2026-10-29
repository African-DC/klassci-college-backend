from app.services.pdf.timetable import _visible_special_labels


def test_non_hour_labels_do_not_collide_with_hour_ticks():
    hours = [9 * 60, 10 * 60, 11 * 60, 12 * 60]
    assert _visible_special_labels({590, 610, 665}, hours, 1.0) == []


def test_spaced_labels_are_kept_in_time_order():
    hours = [9 * 60, 10 * 60, 11 * 60, 12 * 60]
    assert _visible_special_labels({570, 630, 675}, hours, 1.0) == [570, 630, 675]


def test_dense_pdf_suppresses_collisions_at_reduced_scale():
    hours = [8 * 60, 9 * 60, 10 * 60]
    assert _visible_special_labels({510, 515, 520}, hours, 0.45) == [510]
