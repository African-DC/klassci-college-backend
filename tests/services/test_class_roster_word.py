"""Vérifie les champs et le format éditable de la liste Word de classe."""

from datetime import date
from io import BytesIO

from docx import Document

from app.services.class_roster_service import _word_roster_document


def test_word_roster_has_requested_columns_and_values():
    payload = {
        "class_name": "6ème A",
        "academic_year_name": "2026-2027",
        "students": [
            {
                "enrollment_number": "RST-001",
                "last_name": "KOUAME",
                "first_name": "Amenan",
                "genre": "F",
                "birth_date": date(2013, 4, 2),
                "birth_place": "Bouaké",
                "nationality": "Ivoirienne",
                "is_repeater": False,
                "assignment_status": "affecte",
            },
        ],
    }
    document = Document(BytesIO(_word_roster_document(payload)))
    assert document.sections[0].page_width > document.sections[0].page_height
    assert len(document.tables) == 2
    table = document.tables[1]
    assert [c.text for c in table.rows[0].cells] == [
        "N°",
        "Matricule",
        "Nom",
        "Prénoms",
        "Sexe",
        "Date de naissance",
        "Lieu de naissance",
        "Nationalité",
        "Qualité",
        "Statut",
    ]
    assert [c.text for c in table.rows[1].cells] == [
        "1",
        "RST-001",
        "KOUAME",
        "Amenan",
        "F",
        "02/04/2013",
        "Bouaké",
        "Ivoirienne",
        "Non redoublant",
        "Affecté",
    ]


def test_word_roster_leaves_missing_fields_blank():
    data = {
        "class_name": "5ème B",
        "academic_year_name": "2026-2027",
        "students": [
            {
                "enrollment_number": None,
                "last_name": "YAO",
                "first_name": "N.",
                "genre": None,
                "birth_date": None,
                "birth_place": None,
                "nationality": None,
                "is_repeater": None,
                "assignment_status": None,
            },
        ],
    }
    row = Document(BytesIO(_word_roster_document(data))).tables[1].rows[1]
    assert [c.text for c in row.cells][4:] == ["", "", "", "", "", ""]


def test_word_roster_uses_tenant_identity():
    payload = {
        "class_name": "4ème A",
        "academic_year_name": "2026-2027",
        "students": [],
        "school_settings": {
            "school_name": "COLLÈGE EXEMPLE",
            "drena_name": "DRENA BOUAKÉ",
            "ministry_code": "CI-123",
            "address": "Quartier administratif",
            "phone": "0102030405",
            "email": "secretariat@example.org",
            "website": "https://example.org",
            "motto": "Travail et réussite",
            "primary_color": "#0453CB",
            "accent_color": "#F58220",
        },
    }
    document = Document(BytesIO(_word_roster_document(payload)))
    text = " ".join(
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    )
    for expected in (
        "COLLÈGE EXEMPLE",
        "DRENA BOUAKÉ",
        "CI-123",
        "Quartier administratif",
        "0102030405",
        "secretariat@example.org",
        "Travail et réussite",
    ):
        assert expected in text
    assert document.tables[0].cell(0, 1).paragraphs[0].runs[0].font.color.rgb is not None
