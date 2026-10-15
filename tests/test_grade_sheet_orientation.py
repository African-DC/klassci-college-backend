"""Tests ciblés du rendu A4 des feuilles de notes."""

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.pdf.grade_sheet import generate_grade_sheet_pdf


def test_grade_sheet_orientation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    class FakeHTML:
        def __init__(self, *, string: str) -> None:
            captured.append(string)

        def write_pdf(self) -> bytes:
            return b"pdf"

    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=FakeHTML))

    student = {
        "enrollment_number": "CI-001",
        "last_name": "Kouassi",
        "first_name": "Awa",
    }
    for orientation in ("portrait", "landscape"):
        result = generate_grade_sheet_pdf(
            {}, {"class_name": "4e A"}, [student], orientation=orientation
        )
        html = captured[-1]
        assert result == b"pdf"
        assert f"size: A4 {orientation};" in html
        assert "Kouassi" in html
        assert "CI-001" in html
        assert html.count("<th>Note ") == 6
        assert "border-left: 0.75px solid var(--border);" in html

    generate_grade_sheet_pdf({}, {}, [])
    assert "size: A4 landscape;" in captured[-1]


def test_grade_sheet_rejects_unsupported_orientation() -> None:
    invalid: Any = "diagonal"
    with pytest.raises(ValueError, match="Orientation"):
        generate_grade_sheet_pdf({}, {}, [], orientation=invalid)
