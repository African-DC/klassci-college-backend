"""PDF and API timetable consistency regression tests."""

import pytest

from app.schemas.timetable import TimetableConfigResponse


def test_configuration_contract():
    config = TimetableConfigResponse(
        slot_duration_minutes=45, day_start_hour=6, day_end_hour=19
    )
    assert config.day_start_hour == 6
    assert config.slot_duration_minutes == 45


def test_pdf_keeps_full_school_day_and_normalizes_labels(monkeypatch):
    from app.services.pdf import timetable

    # Pure HTML inspection without depending on rendering/GTK in CI.
    captured = {}

    class FakeHTML:
        def __init__(self, *, string):
            captured["html"] = string

        def write_pdf(self):
            return b"%PDF-stub"

    # WeasyPrint is loaded lazily from this module at invocation time; patch
    # only if the installed dependency is available.
    wp = pytest.importorskip("weasyprint")
    monkeypatch.setattr(wp, "HTML", FakeHTML)

    original = timetable.ui.premium_header
    monkeypatch.setattr(timetable.ui, "premium_header", lambda *a, **kw: "")
    monkeypatch.setattr(timetable.ui, "premium_footer", lambda *a, **kw: "")
    monkeypatch.setattr(timetable.ui, "base_styles", lambda *a, **kw: "")

    monkeypatch.setattr(timetable.PDFTheme, "from_school", lambda *_: object())
    result = timetable.generate_timetable_pdf(
        slots=[
            {"day": "friday", "start_time": "08:00", "end_time": "09:50",
             "subject_name": "SVT", "teacher_name": "NANA JACQUES"},
            {"day": "monday", "start_time": "10:10", "end_time": "11:05",
             "subject_name": "Anglais", "teacher_name": "YAPI ACHI PACOME"},
        ],
        class_name="6ème 1",
        academic_year="2026-2027",
        school_settings={},
        day_start=7,
        day_end=17,
    )
    assert result == b"%PDF-stub"
    html = captured["html"]
    assert "07:00" in html and "17:00" in html
    assert "NANA JACQUES" in html
    # Time labels near 10:00 must not collide in the gutter.
    assert 'tt-hlabel-soft' in html
    assert '>10:10</div>' not in html
