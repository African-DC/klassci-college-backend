"""Répartition des tranches et calcul du retard — les deux règles contestables."""

from datetime import date
from decimal import Decimal

from app.services.installments._math import (
    compute_arrears,
    is_complete_grid,
    split_by_percentage,
)

D = Decimal


# ---------------------------------------------------------------------------
# Répartition
# ---------------------------------------------------------------------------


def test_split_never_loses_nor_creates_a_franc() -> None:
    """Trois tiers sur 100 000 doivent retomber exactement sur 100 000."""
    amounts = split_by_percentage(D("100000"), [D("33.33"), D("33.33"), D("33.34")])
    assert sum(amounts) == D("100000")


def test_last_installment_absorbs_the_rounding() -> None:
    amounts = split_by_percentage(D("100000"), [D("33.33"), D("33.33"), D("33.34")])
    assert amounts[0] == D("33330")
    assert amounts[1] == D("33330")
    assert amounts[2] == D("33340")


def test_split_follows_each_student_own_total() -> None:
    """Une 6e et une Terminale suivent la même grille sans double saisie."""
    grid = [D("40"), D("30"), D("30")]
    sixieme = split_by_percentage(D("200000"), grid)
    terminale = split_by_percentage(D("350000"), grid)
    assert sixieme == [D("80000"), D("60000"), D("60000")]
    assert terminale == [D("140000"), D("105000"), D("105000")]
    assert sum(terminale) == D("350000")


def test_split_handles_a_single_installment() -> None:
    assert split_by_percentage(D("75000"), [D("100")]) == [D("75000")]


def test_split_of_an_empty_grid_is_empty() -> None:
    assert split_by_percentage(D("75000"), []) == []


def test_grid_must_total_one_hundred() -> None:
    assert is_complete_grid([D("40"), D("30"), D("30")])
    assert not is_complete_grid([D("40"), D("30")])
    assert not is_complete_grid([D("40"), D("30"), D("40")])
    assert not is_complete_grid([])


# ---------------------------------------------------------------------------
# Retard — le point sur lequel Marcel a insisté
# ---------------------------------------------------------------------------


SCHEDULE = [
    (date(2026, 11, 30), D("80000")),
    (date(2027, 1, 31), D("60000")),
    (date(2027, 3, 31), D("60000")),
]


def test_paying_in_instalments_is_not_being_late() -> None:
    """Le piège à éviter : marquer impayé une famille parfaitement à jour."""
    arrears = compute_arrears(SCHEDULE, paid=D("80000"), today=date(2026, 12, 15))
    assert not arrears.is_late
    assert arrears.due_so_far == D("80000")
    assert arrears.late_amount == D("0")


def test_nothing_is_due_before_the_first_deadline() -> None:
    arrears = compute_arrears(SCHEDULE, paid=D("0"), today=date(2026, 10, 1))
    assert not arrears.is_late
    assert arrears.due_so_far == D("0")
    assert arrears.next_due_date == date(2026, 11, 30)
    assert arrears.next_due_amount == D("80000")


def test_late_only_counts_what_is_already_due() -> None:
    """Au 15 février, deux échéances sont passées, pas la troisième."""
    arrears = compute_arrears(SCHEDULE, paid=D("100000"), today=date(2027, 2, 15))
    assert arrears.due_so_far == D("140000")
    assert arrears.late_amount == D("40000")
    assert arrears.is_late


def test_paying_ahead_is_never_a_negative_arrear() -> None:
    arrears = compute_arrears(SCHEDULE, paid=D("200000"), today=date(2026, 12, 1))
    assert arrears.late_amount == D("0")
    assert not arrears.is_late


def test_deadline_day_itself_is_already_due() -> None:
    """Le jour de l'échéance, la tranche est exigible — pas le lendemain."""
    arrears = compute_arrears(SCHEDULE, paid=D("0"), today=date(2026, 11, 30))
    assert arrears.due_so_far == D("80000")
    assert arrears.is_late


def test_no_schedule_means_no_arrears() -> None:
    """Une école qui n'a pas configuré ses tranches ne doit accuser personne."""
    arrears = compute_arrears([], paid=D("0"), today=date(2027, 6, 1))
    assert not arrears.is_late
    assert arrears.due_so_far == D("0")
    assert arrears.next_due_date is None


# ---------------------------------------------------------------------------
# Qui peut faire quoi sur les tranches
# ---------------------------------------------------------------------------


def test_only_finance_roles_may_change_the_grid() -> None:
    """Lire les échéances est un service au guichet, les fixer est financier."""
    from app.services.tenants.permissions import ROLE_DEFINITIONS

    for role in ("cashier", "educator", "staff"):
        perms = set(ROLE_DEFINITIONS[role]["permissions"])
        assert "admin:fee-installments:read" in perms, f"{role} doit pouvoir répondre à un parent"
        assert "admin:fee-installments:write" not in perms
        assert "enrollments:schedule:write" not in perms

    accountant = set(ROLE_DEFINITIONS["accountant"]["permissions"])
    assert "admin:fee-installments:write" in accountant
    assert "enrollments:schedule:write" in accountant


def test_studies_director_stays_out_of_the_instalment_grid() -> None:
    """Aucun accès financier pour le directeur des études, tranches comprises."""
    from app.services.tenants.permissions import ROLE_DEFINITIONS

    perms = set(ROLE_DEFINITIONS["studies_director"]["permissions"])
    financial = {p for p in perms if "installment" in p or "schedule" in p}
    assert not financial, f"Le directeur des études ne touche pas aux échéances : {financial}"
