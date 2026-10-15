"""Le format A4 choisi doit produire un vrai PDF portrait ou paysage."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.services.pdf.grade_sheet import generate_grade_sheet_pdf


@pytest.mark.parametrize("orientation", ["portrait", "landscape"])
def test_grade_sheet_orientation_and_writable_grid(
    monkeypatch: pytest.MonkeyPatch, orientation: str
) -> None:
    captured: dict[str, str] = {}

    class HTMLStub:
        def __init__(self, *, string: str) -> None:
            captured["html"] = string

        def write_pdf(self) -> bytes:
            return b"%PDF-1.7"

    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=HTMLStub))
    school = {"name": "College de test"}
    class_info = {
        "class_name": "4eme A",
        "level_name": "4eme",
        "academic_year_name": "2026-2027",
        "effectif": 1,
    }
    students = [
        {"enrollment_number": "CI-001", "last_name": "Kouassi", "first_name": "Awa"}
    ]
    data = generate_grade_sheet_pdf(school, class_info, students, orientation=orientation)

    html = captured["html"]
    assert data == b"%PDF-1.7"
    assert f"size: A4 {orientation};" in html
    assert "Kouassi" in html
    assert "CI-001" in html
    assert html.count("<th>Note ") == 6
    assert "border-left: 0.75px solid var(--border)" in html
    assert "border-left: 0.75px solid var(--border);\n        }}" in html


def test_grade_sheet_defaults_to_landscape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class HTMLStub:
        def __init__(self, *, string: str) -> None:
            captured["html"] = string

        def write_pdf(self) -> bytes:
            return b"%PDF-1.7"

    monkeypatch.setitem(sys.modules, "weasyprint", SimpleNamespace(HTML=HTMLStub))
    generate_grade_sheet_pdf({}, {}, [])
    assert "size: A4 landscape;" in captured["html"]


def test_grade_sheet_rejects_unsupported_orientation() -> None:
    with pytest.raises(ValueError, match="Orientation"):
        generate_grade_sheet_pdf({}, {}, [], orientation="diagonal")  # type: ignore[arg-type]
