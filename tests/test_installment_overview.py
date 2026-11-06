"""La liste et les exports ne doivent pas inventer un autre calcul de retard."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.repositories.installment_overview_repository import EnrollmentIdentity
from app.services.installments import overview as overview_module


@pytest.mark.asyncio
async def test_overview_standard_negotiated_and_server_filter(monkeypatch):
    people = [
        EnrollmentIdentity(1, "Awa", "Koné", "CI001", 10, "6e A"),
        EnrollmentIdentity(2, "Ali", "Touré", "CI002", 10, "6e A"),
    ]

    async def identities(_db, **_kwargs):
        return people

    async def due(_db, _ids):
        return {1: Decimal("100"), 2: Decimal("50")}

    async def paid(_db, _ids):
        return {1: Decimal("10"), 2: Decimal("50")}

    async def plans(_db, _ids):
        return {
            2: [
                SimpleNamespace(
                    enrollment_id=2,
                    name="Accord",
                    position=1,
                    due_date=date(2999, 1, 1),
                    amount=Decimal("50"),
                )
            ]
        }

    async def grid(_db, _year):
        return [
            SimpleNamespace(
                kind="fixed",
                amount=Decimal("20"),
                percentage=None,
                due_date=date(2000, 1, 1),
            ),
            SimpleNamespace(
                kind="percentage",
                amount=None,
                percentage=Decimal("100"),
                due_date=date(2999, 1, 1),
            ),
        ]

    monkeypatch.setattr(overview_module.repo, "list_identities", identities)
    monkeypatch.setattr(overview_module.repo, "mandatory_totals", due)
    monkeypatch.setattr(overview_module.repo, "mandatory_paid", paid)
    monkeypatch.setattr(overview_module.repo, "negotiated_plans", plans)
    monkeypatch.setattr(overview_module.installment_repository, "list_year_grid", grid)

    result = await overview_module.overview(None, academic_year_id=7, page=2, size=1)
    assert result.total == 2
    assert result.totals.enrollments == 2
    assert result.totals.late_enrollments == 1
    assert result.totals.total_late == 10
    assert result.items[0].enrollment_id == 2
    assert result.items[0].state == "settled"
    assert result.items[0].source == "negotiated"

    late = await overview_module.overview(None, academic_year_id=7, state="late")
    assert late.total == 1
    assert late.items[0].enrollment_id == 1
    assert late.items[0].due_so_far == 20
    assert late.items[0].late_amount == 10


@pytest.mark.parametrize(
    ("source", "due", "paid", "late", "not_planned", "expected"),
    [
        ("none", 100, 0, 0, 100, "unconfigured"),
        ("standard", 100, 40, 20, 0, "late"),
        ("standard", 100, 40, 0, 30, "partial_schedule"),
        ("standard", 100, 100, 0, 0, "settled"),
        ("standard", 100, 40, 0, 0, "on_track"),
        ("none", 0, 0, 0, 0, "no_fees"),
    ],
)
def test_status_does_not_confuse_total_debt_with_late_debt(
    source, due, paid, late, not_planned, expected
):
    assert (
        overview_module._status(
            source=source,
            due=Decimal(due),
            paid=Decimal(paid),
            late=Decimal(late),
            unscheduled=Decimal(not_planned),
        )
        == expected
    )


def test_xlsx_export_lists_every_filtered_row_with_totals() -> None:
    """Le classeur reprend toutes les lignes reçues, pas seulement une page."""
    from io import BytesIO

    from openpyxl import load_workbook

    from app.schemas.installment_overview import (
        ScheduleOverviewResponse,
        ScheduleOverviewRow,
        ScheduleOverviewTotals,
    )
    from app.services.installments.overview_documents import generate_overview_xlsx

    rows = [
        ScheduleOverviewRow(
            enrollment_id=i,
            student_name=f"ÉLÈVE {i}",
            matricule=f"CI-{i:03d}",
            class_id=1,
            class_name="6e A",
            source="standard",
            state="late" if i % 2 else "on_track",
            total_due=100000,
            total_paid=40000,
            remaining=60000,
            due_so_far=50000,
            late_amount=10000 if i % 2 else 0,
            unscheduled_amount=0,
        )
        for i in range(1, 26)
    ]
    data = ScheduleOverviewResponse(
        items=rows,
        total=25,
        page=1,
        size=5000,
        totals=ScheduleOverviewTotals(
            enrollments=25,
            late_enrollments=13,
            total_due=2_500_000,
            total_paid=1_000_000,
            total_remaining=1_500_000,
            total_late=130_000,
        ),
    )
    from datetime import datetime

    contenu = generate_overview_xlsx(
        data,
        {"school_name": "Collège test"},
        year="2025-2026",
        class_name="",
        search="",
        state="all",
        issued_at=datetime(2026, 11, 6, 10, 0),
    )
    feuille = load_workbook(BytesIO(contenu)).active
    valeurs = [c for r in feuille.iter_rows(values_only=True) for c in r if c is not None]

    assert sum(1 for v in valeurs if isinstance(v, str) and v.startswith("CI-")) == 25
    assert "CI-025" in valeurs
