"""Tests du plan de l'école de démonstration : ce qui est calculé, pas les données.

On ne teste pas « il y a six cents élèves » : ce serait figer un chiffre qu'on
change en une ligne. On teste les règles qui, si elles cassent, donnent une
démonstration fausse sans que personne ne s'en aperçoive : les montants de la
brochure, l'échéancier qu'ils produisent, le rapprochement des libellés
existants, et le dimensionnement de l'équipe enseignante.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.cli.seed_demo import cashdesk, names, plan, portraits, staffing
from app.cli.seed_demo.billing import _installment_lines
from app.cli.seed_demo.context import SeedContext
from app.services.installments import GridLine, resolve_grid_amounts

# ---------------------------------------------------------------------------
# Rapprochement des libellés déjà en base
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("6ème", "6eme"),
        ("N'Guessan", "nguessan"),
        ("Tle A", "tlea"),
        ("  1ère   C ", "1erec"),
    ],
)
def test_normalize_reduit_aux_lettres_et_chiffres(raw: str, expected: str) -> None:
    assert plan.normalize(raw) == expected


@pytest.mark.parametrize(
    ("canonical", "existing"),
    [
        ("Terminale", "Terminal"),
        ("Terminale", "Tle"),
        ("2nde", "Seconde"),
        ("1ère", "première"),
        ("6ème", "6eme"),
    ],
)
def test_un_niveau_deja_saisi_autrement_est_reconnu(canonical: str, existing: str) -> None:
    """Sans ce rapprochement, le semis ouvrirait une seconde Terminale."""
    assert plan.normalize(existing) in plan.level_aliases(canonical)


@pytest.mark.parametrize(("raw", "letter"), [("serie A", "A"), ("Série C", "C"), ("D", "D")])
def test_serie_reconnue_quelle_que_soit_sa_graphie(raw: str, letter: str) -> None:
    assert plan.series_token(raw) == letter


def test_division_lue_sur_le_dernier_mot_du_nom() -> None:
    assert plan.division_token("Tle A") == "A"
    assert plan.division_token("6ème B") == "B"


# ---------------------------------------------------------------------------
# Structure de l'établissement
# ---------------------------------------------------------------------------


def test_le_plan_de_classes_est_sans_doublon() -> None:
    entries = plan.class_plan()
    assert len(entries) == len(set(entries))


def test_toute_classe_de_lycee_porte_une_serie_et_toute_classe_de_college_non() -> None:
    for level, serie, division in plan.class_plan():
        if level in plan.SERIES:
            assert serie is not None
            assert serie == division, "au lycée, la série tient lieu de division"
        else:
            assert serie is None


def test_chaque_classe_ouverte_a_un_programme_utilisable() -> None:
    """Une classe sans programme ne peut recevoir ni note ni emploi du temps."""
    for level, serie, _division in plan.class_plan():
        entries = plan.curriculum_for(level, serie)
        assert entries, f"{level} {serie} sans programme"
        assert all(coefficient > 0 and hours > 0 for _n, coefficient, hours in entries)
        names_seen = [name for name, _c, _h in entries]
        assert len(names_seen) == len(set(names_seen)), "matière en double dans un programme"


def test_la_philosophie_n_ouvre_qu_en_terminale() -> None:
    for level, serie, _division in plan.class_plan():
        subjects = {name for name, _c, _h in plan.curriculum_for(level, serie)}
        assert ("Philosophie" in subjects) == (level == "Terminale")


# ---------------------------------------------------------------------------
# La grille tarifaire de la brochure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "scolarite"),
    [
        ("6ème", "70000"),
        ("5ème", "70000"),
        ("4ème", "90000"),
        ("3ème", "110000"),
        ("2nde", "100000"),
        ("1ère", "100000"),
        ("Terminale", "120000"),
    ],
)
def test_la_scolarite_de_chaque_niveau_est_celle_de_la_brochure(level: str, scolarite: str) -> None:
    grid = plan.fees_for_level(level)
    assert grid["Scolarité"] == Decimal(scolarite)
    assert grid["Inscription"] == Decimal("37000")
    assert grid["Tenue scolaire"] == Decimal("18000")


def test_soutien_et_droit_d_examen_ne_touchent_que_les_classes_d_examen() -> None:
    for level, _order, _aliases in plan.LEVELS:
        grid = plan.fees_for_level(level)
        expected = level in {"3ème", "Terminale"}
        assert ("Cours de soutien" in grid) is expected
        assert ("Droit d'examen" in grid) is expected

    assert plan.fees_for_level("3ème")["Droit d'examen"] == Decimal("2000")
    assert plan.fees_for_level("Terminale")["Droit d'examen"] == Decimal("5000")


def test_un_eleve_affecte_ne_doit_pas_la_scolarite() -> None:
    """C'est l'État qui la prend en charge : la démonstration doit le montrer."""
    assert plan.total_due("6ème", subsidised=False) == Decimal("125000")
    assert plan.total_due("6ème", subsidised=True) == Decimal("55000")
    assert plan.total_due("Terminale", subsidised=False) == Decimal("198000")
    assert plan.total_due("Terminale", subsidised=True) == Decimal("78000")


# ---------------------------------------------------------------------------
# L'échéancier que cette grille produit
# ---------------------------------------------------------------------------


def test_les_pourcentages_de_la_grille_totalisent_cent() -> None:
    percentages = [
        value for _n, _p, is_fixed, value, _m, _d in plan.INSTALLMENT_GRID if not is_fixed
    ]
    assert sum(percentages) == Decimal("100")


def test_les_echeances_de_janvier_et_mars_tombent_l_annee_civile_suivante() -> None:
    """Sans ce décalage, tout l'échéancier daterait d'un an trop tôt."""
    due_dates = [line.due_date for line in _installment_lines(2025)]
    assert due_dates == [
        date(2025, 9, 15),
        date(2025, 11, 30),
        date(2026, 1, 31),
        date(2026, 3, 31),
    ]


def test_l_echeancier_d_une_sixieme_non_affectee_est_celui_de_la_brochure() -> None:
    """37 000 F à la rentrée, puis 35 / 35 / 30 % des 88 000 F restants."""
    lines = [
        GridLine(is_fixed=line.kind == "fixed", value=Decimal(str(line.amount or line.percentage)))
        for line in _installment_lines(2025)
    ]
    amounts = resolve_grid_amounts(plan.total_due("6ème", subsidised=False), lines)
    assert amounts == [
        Decimal("37000"),
        Decimal("30800"),
        Decimal("30800"),
        Decimal("26400"),
    ]
    assert sum(amounts) == plan.total_due("6ème", subsidised=False)


def test_l_echeancier_d_un_affecte_ne_reclame_jamais_plus_qu_il_ne_doit() -> None:
    lines = [
        GridLine(is_fixed=line.kind == "fixed", value=Decimal(str(line.amount or line.percentage)))
        for line in _installment_lines(2025)
    ]
    total = plan.total_due("6ème", subsidised=True)
    amounts = resolve_grid_amounts(total, lines)
    assert sum(amounts) == total
    assert amounts[0] == Decimal("37000")


# ---------------------------------------------------------------------------
# Dimensionnement de l'équipe et calendrier
# ---------------------------------------------------------------------------


def test_l_equipe_enseignante_couvre_les_heures_a_assurer() -> None:
    """Sous-dimensionner l'équipe rend l'emploi du temps inconstructible."""
    hours: dict[str, int] = {}
    for level, serie, _division in plan.class_plan():
        for name, _coefficient, weekly in plan.curriculum_for(level, serie):
            hours[name] = hours.get(name, 0) + weekly

    headcount = staffing._teacher_headcount()
    assert set(headcount) == set(hours)
    for subject, total in hours.items():
        assert headcount[subject] >= 1
        assert total / headcount[subject] <= staffing.WEEKLY_LOAD


def _context() -> SeedContext:
    ctx = SeedContext(db=None, tenant="test", today=date(2026, 8, 21), actor_id=1)  # type: ignore[arg-type]
    ctx.trimesters = [
        (1, date(2025, 9, 1), date(2025, 12, 19)),
        (2, date(2026, 1, 5), date(2026, 4, 3)),
        (3, date(2026, 4, 13), date(2026, 6, 30)),
    ]
    return ctx


def test_les_jours_d_appel_tombent_en_semaine_et_dans_le_trimestre() -> None:
    ctx = _context()
    for trimester, start, end in ctx.trimesters:
        days = ctx.school_days(trimester, 6)
        assert len(days) == 6
        assert days == sorted(days)
        assert all(start <= day <= end for day in days)
        assert all(day.weekday() < 5 for day in days)


def test_une_date_est_rattachee_a_son_trimestre() -> None:
    ctx = _context()
    assert ctx.trimester_of(date(2025, 10, 3)) == 1
    assert ctx.trimester_of(date(2026, 2, 10)) == 2
    assert ctx.trimester_of(date(2026, 5, 20)) == 3


def test_le_matricule_est_stable_et_jamais_vide() -> None:
    ctx = _context()
    assert ctx.matricule(7) == "KLS26-0007"
    assert ctx.matricule(7) == ctx.matricule(7)


# ---------------------------------------------------------------------------
# Identités
# ---------------------------------------------------------------------------


def test_une_adresse_de_demonstration_ne_contient_ni_accent_ni_apostrophe() -> None:
    address = names.email_for("Aïssatou", "N'Guessan", 12, "demo.klassci.ci")
    assert address == "aissatou.nguessan12@demo.klassci.ci"


def test_deux_homonymes_n_entrent_pas_en_collision() -> None:
    first = names.email_for("Yao", "Koné", 3, "demo.klassci.ci")
    second = names.email_for("Yao", "Koné", 4, "demo.klassci.ci")
    assert first != second


def test_les_initiales_tiennent_sur_deux_lettres() -> None:
    assert portraits.initials("Aminata", "Traoré") == "AT"
    assert portraits.initials("Yao", "") == "Y"


# ---------------------------------------------------------------------------
# Ce qui rend le semis relançable
# ---------------------------------------------------------------------------


def test_chaque_etape_a_son_propre_tirage() -> None:
    """Un tirage ajouté dans une étape ne doit pas décaler les suivantes."""
    first = _context()
    second = _context()
    first.reseed("cashdesk")
    second.reseed("cashdesk")
    assert [first.rng.random() for _ in range(5)] == [second.rng.random() for _ in range(5)]

    other = _context()
    other.reseed("presence")
    assert other.rng.random() != second.rng.random()


def test_le_plan_de_reglement_ne_depend_que_de_l_inscription() -> None:
    """Il doit être identique avant et après que la famille ait versé.

    C'est la garantie qui empêche une seconde exécution d'encaisser une
    deuxième fois toute l'année.
    """
    amounts = [Decimal("37000"), Decimal("70000"), Decimal("18000")]
    for enrollment_id in (1, 42, 517):
        first = cashdesk._plan_for(enrollment_id, amounts)
        second = cashdesk._plan_for(enrollment_id, amounts)
        assert first == second


def test_un_plan_de_reglement_ne_reclame_jamais_plus_que_la_dette() -> None:
    amounts = [Decimal("37000"), Decimal("120000"), Decimal("18000")]
    total = sum(amounts, Decimal("0"))
    for enrollment_id in range(1, 200):
        lines = cashdesk._plan_for(enrollment_id, amounts)
        assert sum(amount for _rank, amount, _method in lines) <= total
        assert all(amount > 0 for _rank, amount, _method in lines)


def test_les_references_de_versement_sont_toutes_distinctes() -> None:
    """Deux versements qui partageraient une référence n'en feraient qu'un."""
    amounts = [Decimal("37000"), Decimal("70000"), Decimal("18000")]
    seen: set[str] = set()
    for enrollment_id in range(1, 300):
        for rank, _amount, method in cashdesk._plan_for(enrollment_id, amounts):
            reference = cashdesk._reference(method, enrollment_id, rank)
            assert reference not in seen
            seen.add(reference)


def test_une_famille_sans_versement_existe_dans_le_lot() -> None:
    """Les écrans d'impayés n'ont rien à montrer sur une école à jour."""
    amounts = [Decimal("37000"), Decimal("70000"), Decimal("18000")]
    plans = [cashdesk._plan_for(enrollment_id, amounts) for enrollment_id in range(1, 300)]
    assert any(not lines for lines in plans)
    assert any(sum(a for _r, a, _m in lines) == sum(amounts) for lines in plans if lines)
