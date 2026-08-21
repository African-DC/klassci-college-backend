"""Une grille qui mélange francs et pourcentages, et l'échéancier qu'elle produit.

Le cas qui a motivé ce travail est celui de la brochure de l'école pilote :
« Aucun élève ne sera admis en classe sans avoir payé l'intégralité de son
inscription », suivi d'un tableau de tranches qui ne couvre que la scolarité.
Exprimée uniquement en pourcentages, cette grille annonçait 43 750 F fin
novembre là où l'école attend 37 000 F à la rentrée puis 30 800 F fin novembre.

Ces tests appellent les fonctions réelles : le calcul pur d'un côté, la
résolution complète de l'échéancier de l'autre, avec l'accès base remplacé par
des doublures. Aucun ne relit du code source à la recherche d'un littéral — ce
serait figer le comportement au lieu de le vérifier.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.installment import FeeInstallmentKind
from app.schemas.installment import FeeInstallmentGridUpdate, FeeInstallmentInput
from app.services.installments._math import GridLine, resolve_grid_amounts
from app.services.installments.schedule import resolve_schedule

D = Decimal

# Les chiffres de la brochure, pour une 6e non affectée.
INSCRIPTION = D("37000")
SCOLARITE = D("70000")
TENUE = D("18000")
TOTAL_BROCHURE = INSCRIPTION + SCOLARITE + TENUE  # 125 000


def _pct(value: str) -> GridLine:
    return GridLine(is_fixed=False, value=D(value))


def _fixe(value: str) -> GridLine:
    return GridLine(is_fixed=True, value=D(value))


# ---------------------------------------------------------------------------
# Le calcul pur
# ---------------------------------------------------------------------------


def test_le_cas_de_la_brochure_tombe_sur_les_chiffres_de_lecole() -> None:
    """37 000 à l'inscription, puis 35 / 35 / 30 % des 88 000 restants."""
    amounts = resolve_grid_amounts(
        TOTAL_BROCHURE,
        [_fixe("37000"), _pct("35"), _pct("35"), _pct("30")],
    )
    assert amounts == [D("37000"), D("30800"), D("30800"), D("26400")]
    assert sum(amounts) == TOTAL_BROCHURE


def test_le_pourcentage_porte_sur_le_reste_pas_sur_le_total() -> None:
    """Le bug d'origine : 35 % de 125 000 font 43 750, pas 30 800."""
    amounts = resolve_grid_amounts(
        TOTAL_BROCHURE,
        [_fixe("37000"), _pct("35"), _pct("35"), _pct("30")],
    )
    assert amounts[1] != D("43750")
    assert amounts[1] == D("30800")


def test_une_grille_en_pourcentages_donne_exactement_ce_quelle_donnait() -> None:
    """Non négociable : aucune école déjà configurée ne voit son calendrier bouger."""
    for total in (D("125000"), D("200000"), D("350000"), D("87500")):
        mixte = resolve_grid_amounts(total, [_pct("35"), _pct("35"), _pct("30")])
        attendu = [
            (total * D("35") / D("100")).quantize(D("1")),
            (total * D("35") / D("100")).quantize(D("1")),
            None,  # la dernière absorbe l'arrondi, comme avant
        ]
        attendu[2] = total - attendu[0] - attendu[1]
        assert mixte == attendu, f"total {total}"
        assert sum(mixte) == total


def test_larrondi_reste_absorbe_par_la_derniere_tranche() -> None:
    """Trois tiers sur ce qui reste doivent retomber sur ce qui reste."""
    amounts = resolve_grid_amounts(
        D("100001"), [_fixe("1"), _pct("33.33"), _pct("33.33"), _pct("33.34")]
    )
    assert sum(amounts) == D("100001")
    assert amounts[0] == D("1")


def test_une_grille_entierement_en_francs_est_legitime() -> None:
    """Une école qui annonce le même échéancier à tous ses élèves."""
    amounts = resolve_grid_amounts(TOTAL_BROCHURE, [_fixe("37000"), _fixe("44000"), _fixe("44000")])
    assert amounts == [D("37000"), D("44000"), D("44000")]


def test_un_montant_ferme_ne_reclame_jamais_plus_que_leleve_ne_doit() -> None:
    """Un affecté subventionné ne paie pas la grille d'un non affecté.

    La grille annonce 37 000 puis 44 000 puis 44 000. Un élève dont les frais
    obligatoires s'élèvent à 60 000 doit 60 000, pas 125 000 : la deuxième
    échéance est ramenée à ce qui reste, la troisième tombe à zéro.
    """
    amounts = resolve_grid_amounts(D("60000"), [_fixe("37000"), _fixe("44000"), _fixe("44000")])
    assert amounts == [D("37000"), D("23000"), D("0")]
    assert sum(amounts) == D("60000")


def test_les_pourcentages_se_partagent_zero_quand_les_francs_ont_tout_pris() -> None:
    amounts = resolve_grid_amounts(D("37000"), [_fixe("37000"), _pct("50"), _pct("50")])
    assert amounts == [D("37000"), D("0"), D("0")]


def test_une_grille_vide_ne_produit_aucune_echeance() -> None:
    assert resolve_grid_amounts(TOTAL_BROCHURE, []) == []


def test_un_eleve_entierement_exonere_ne_doit_rien() -> None:
    """Total à zéro : les montants fermes ne doivent pas ressusciter une dette."""
    amounts = resolve_grid_amounts(D("0"), [_fixe("37000"), _pct("100")])
    assert amounts == [D("0"), D("0")]


# ---------------------------------------------------------------------------
# La validation de la grille
# ---------------------------------------------------------------------------


def _ligne_pct(name: str, position: int, percentage: float, due: str) -> FeeInstallmentInput:
    return FeeInstallmentInput(
        name=name, position=position, percentage=percentage, due_date=date.fromisoformat(due)
    )


def _ligne_fixe(name: str, position: int, amount: float, due: str) -> FeeInstallmentInput:
    return FeeInstallmentInput(
        name=name,
        position=position,
        kind=FeeInstallmentKind.FIXED,
        amount=amount,
        due_date=date.fromisoformat(due),
    )


def test_une_tranche_ne_porte_pas_les_deux_ecritures() -> None:
    """Sinon le calcul en choisirait une en silence, et l'écran mentirait."""
    with pytest.raises(ValueError):
        FeeInstallmentInput(
            name="Inscription",
            position=1,
            kind=FeeInstallmentKind.FIXED,
            amount=37000,
            percentage=35,
            due_date=date(2026, 9, 1),
        )


def test_une_tranche_en_francs_exige_un_montant() -> None:
    with pytest.raises(ValueError):
        FeeInstallmentInput(
            name="Inscription",
            position=1,
            kind=FeeInstallmentKind.FIXED,
            due_date=date(2026, 9, 1),
        )


def test_une_tranche_sans_type_reste_un_pourcentage() -> None:
    """Rétrocompatible : un appel qui n'envoie qu'un pourcentage marche encore."""
    ligne = _ligne_pct("Tranche 1", 1, 35, "2026-11-30")
    assert ligne.kind is FeeInstallmentKind.PERCENTAGE
    assert ligne.amount is None


async def test_la_grille_refuse_des_pourcentages_qui_ne_font_pas_cent(monkeypatch) -> None:
    from app.services.installments import grid as grid_service

    data = FeeInstallmentGridUpdate(
        installments=[
            _ligne_fixe("Inscription", 1, 37000, "2026-09-01"),
            _ligne_pct("Fin novembre", 2, 35, "2026-11-30"),
            _ligne_pct("Fin décembre", 3, 35, "2026-12-31"),
        ]
    )
    with pytest.raises(HTTPException) as erreur:
        await grid_service.replace_grid(_DbMuette(), 1, data, updated_by=1)
    assert erreur.value.status_code == 422
    assert "70" in str(erreur.value.detail)


async def test_la_grille_accepte_une_suite_de_montants_fermes(monkeypatch) -> None:
    """Sans pourcentage, aucune somme n'est imposée : le total varie par niveau.

    Le garde-fou ne peut pas vivre ici — le total obligatoire n'existe qu'au
    niveau d'un élève. Il vit à la résolution, où un montant ferme est borné
    par ce que l'élève doit réellement.
    """
    from app.services.installments import grid as grid_service

    ecrites: list[dict] = []

    async def _fake_replace(_db, _year, rows):
        ecrites.extend(rows)
        return []

    async def _fake_audit(_db, **_kwargs):
        return None

    async def _fake_list(_db, _year):
        return []

    monkeypatch.setattr(grid_service.repo, "replace_year_grid", _fake_replace)
    monkeypatch.setattr(grid_service.repo, "list_year_grid", _fake_list)
    monkeypatch.setattr(grid_service, "audit_log", _fake_audit)

    data = FeeInstallmentGridUpdate(
        installments=[
            _ligne_fixe("Inscription", 1, 37000, "2026-09-01"),
            _ligne_fixe("Fin novembre", 2, 44000, "2026-11-30"),
        ]
    )
    await grid_service.replace_grid(_DbMuette(), 1, data, updated_by=1)
    assert [row["kind"] for row in ecrites] == ["fixed", "fixed"]
    assert [row["amount"] for row in ecrites] == [37000, 44000]
    assert [row["percentage"] for row in ecrites] == [None, None]


class _DbMuette:
    """Assez de surface pour que le service tourne sans base."""

    def begin_nested(self):
        return _TransactionMuette()

    async def commit(self) -> None:
        return None


class _TransactionMuette:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


# ---------------------------------------------------------------------------
# L'échéancier complet
# ---------------------------------------------------------------------------


class _LigneGrille:
    """Une ligne de `fee_installments` telle que le résolveur la lit."""

    def __init__(
        self,
        name: str,
        position: int,
        due_date: date,
        *,
        percentage: Decimal | None = None,
        amount: Decimal | None = None,
    ) -> None:
        self.name = name
        self.position = position
        self.due_date = due_date
        self.percentage = percentage
        self.amount = amount
        self.kind = "fixed" if amount is not None else "percentage"


def _grille_brochure() -> list[_LigneGrille]:
    return [
        _LigneGrille("À l'inscription", 1, date(2026, 9, 1), amount=INSCRIPTION),
        _LigneGrille("Fin novembre", 2, date(2026, 11, 30), percentage=D("35")),
        _LigneGrille("Fin décembre", 3, date(2026, 12, 31), percentage=D("35")),
        _LigneGrille("Fin janvier", 4, date(2027, 1, 31), percentage=D("30")),
    ]


def _grille_pourcentages() -> list[_LigneGrille]:
    return [
        _LigneGrille("Fin novembre", 1, date(2026, 11, 30), percentage=D("35")),
        _LigneGrille("Fin décembre", 2, date(2026, 12, 31), percentage=D("35")),
        _LigneGrille("Fin janvier", 3, date(2027, 1, 31), percentage=D("30")),
    ]


@pytest.fixture
def echeancier(monkeypatch):
    """Appelle le vrai `resolve_schedule`, avec l'accès base remplacé."""
    from app.services import fees_paid
    from app.services.installments import schedule as schedule_service

    async def _factory(grille, *, paid: Decimal, today: date, total: Decimal = TOTAL_BROCHURE):
        async def _fake_year(_db, _enrollment_id):
            return 1

        async def _fake_total(_db, _enrollment_id):
            return total

        async def _fake_plan(_db, _enrollment_id):
            return []

        async def _fake_grid(_db, _year_id):
            return grille

        async def _fake_paid(_db, _enrollment_id):
            return paid

        monkeypatch.setattr(schedule_service, "_academic_year_id", _fake_year)
        monkeypatch.setattr(schedule_service.repo, "mandatory_total", _fake_total)
        monkeypatch.setattr(schedule_service.repo, "list_enrollment_plan", _fake_plan)
        monkeypatch.setattr(schedule_service.repo, "list_year_grid", _fake_grid)
        monkeypatch.setattr(fees_paid, "paid_on_mandatory", _fake_paid)

        return await resolve_schedule(object(), 4, today=today)

    return _factory


async def test_lecheancier_de_la_brochure_dit_les_montants_de_lecole(echeancier) -> None:
    """37 000 à la rentrée, puis 30 800, 30 800 et 26 400."""
    reponse = await echeancier(_grille_brochure(), paid=D("0"), today=date(2026, 9, 15))

    assert [(ligne.name, ligne.amount) for ligne in reponse.lines] == [
        ("À l'inscription", 37000.0),
        ("Fin novembre", 30800.0),
        ("Fin décembre", 30800.0),
        ("Fin janvier", 26400.0),
    ]
    assert sum(ligne.amount for ligne in reponse.lines) == 125000.0
    assert reponse.unscheduled_amount == 0.0


async def test_une_famille_qui_na_pas_paye_son_inscription_est_en_retard(echeancier) -> None:
    """Le premier jour de classe, l'inscription est exigible et rien n'est versé."""
    reponse = await echeancier(_grille_brochure(), paid=D("0"), today=date(2026, 9, 15))

    assert reponse.is_late
    assert reponse.due_so_far == 37000.0
    assert reponse.late_amount == 37000.0
    assert reponse.next_due_date == date(2026, 11, 30)
    assert reponse.next_due_amount == 30800.0


async def test_une_famille_qui_a_paye_son_inscription_nest_pas_en_retard(echeancier) -> None:
    """Le pendant du test précédent : payer à temps ne doit jamais alerter."""
    reponse = await echeancier(_grille_brochure(), paid=INSCRIPTION, today=date(2026, 9, 15))

    assert not reponse.is_late
    assert reponse.late_amount == 0.0


async def test_fin_novembre_lecole_attend_linscription_plus_la_premiere_tranche(
    echeancier,
) -> None:
    """37 000 + 30 800 = 67 800 exigibles, et non 43 750 comme avant."""
    reponse = await echeancier(_grille_brochure(), paid=D("37000"), today=date(2026, 12, 1))

    assert reponse.due_so_far == 67800.0
    assert reponse.late_amount == 30800.0


async def test_une_ecole_sans_montant_ferme_voit_lecheancier_dhier(echeancier) -> None:
    """Non négociable : une grille 35 / 35 / 30 donne les mêmes francs qu'avant."""
    reponse = await echeancier(_grille_pourcentages(), paid=D("0"), today=date(2026, 9, 15))

    assert [(ligne.name, ligne.amount) for ligne in reponse.lines] == [
        ("Fin novembre", 43750.0),
        ("Fin décembre", 43750.0),
        ("Fin janvier", 37500.0),
    ]
    assert sum(ligne.amount for ligne in reponse.lines) == 125000.0
    assert not reponse.is_late  # rien n'est encore exigible au 15 septembre
    assert reponse.unscheduled_amount == 0.0


async def test_ce_que_la_grille_ne_planifie_pas_est_annonce_sans_etre_reclame(
    echeancier,
) -> None:
    """Une grille en francs qui ne couvre pas tout laisse un reliquat visible.

    Ce reliquat ne rend personne en retard : aucune échéance ne le réclame, et
    inventer une date pour lui reviendrait à accuser une famille sur un
    calendrier que l'école n'a pas défini.
    """
    grille = [_LigneGrille("Inscription", 1, date(2026, 9, 1), amount=INSCRIPTION)]
    reponse = await echeancier(grille, paid=INSCRIPTION, today=date(2027, 6, 1))

    assert reponse.total_mandatory == 125000.0
    assert reponse.unscheduled_amount == 88000.0
    assert not reponse.is_late
