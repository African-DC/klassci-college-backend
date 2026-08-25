"""Cloisonnement financier — qui lit ce qu'une famille doit."""

from app.services.finance_visibility import AMOUNT_FIELDS, FinanceView, redact
from app.services.tenants.permissions import ALL_PERMISSIONS, ROLE_DEFINITIONS


def _perms(role: str) -> set[str]:
    return set(ROLE_DEFINITIONS[role]["permissions"])


# ---------------------------------------------------------------------------
# La décision
# ---------------------------------------------------------------------------


def test_voir_les_montants_implique_voir_l_etat() -> None:
    """Refuser le badge à un comptable faute d'avoir coché la permission la
    plus faible serait absurde."""
    view = FinanceView.of(may_read_payments=True, may_read_status=False)
    assert view.amounts is True
    assert view.status is True


def test_l_etat_seul_ne_donne_pas_les_montants() -> None:
    view = FinanceView.of(may_read_payments=False, may_read_status=True)
    assert view.amounts is False
    assert view.status is True


def test_sans_rien_on_ne_voit_rien() -> None:
    view = FinanceView.of(may_read_payments=False, may_read_status=False)
    assert view.amounts is False
    assert view.status is False


# ---------------------------------------------------------------------------
# La rédaction
# ---------------------------------------------------------------------------


def _block() -> dict:
    return {
        "first_name": "Aminata",
        "fees_expected": 200000.0,
        "fees_paid": 120000.0,
        "fees_remaining": 80000.0,
        "fees_rate": 60.0,
        "fee_status": "en_retard",
        "last_payment_date": "2026-01-12",
    }


def test_les_montants_disparaissent_le_reste_survit() -> None:
    redacted = redact(_block(), FinanceView(amounts=False, status=True))
    for field in ("fees_expected", "fees_paid", "fees_remaining", "fees_rate"):
        assert redacted[field] is None, f"{field} ne doit pas sortir"
    assert redacted["first_name"] == "Aminata"
    assert redacted["fee_status"] == "en_retard", "l'état reste, il ne trahit aucune somme"
    assert redacted["last_payment_date"] == "2026-01-12"


def test_on_renvoie_none_jamais_zero() -> None:
    """Un zéro se lit « la famille ne doit rien » : ce serait un mensonge."""
    redacted = redact(_block(), FinanceView(amounts=False, status=True))
    assert redacted["fees_remaining"] is None
    assert redacted["fees_remaining"] != 0


def test_avec_le_droit_rien_n_est_touche() -> None:
    block = _block()
    assert redact(block, FinanceView(amounts=True, status=True)) == block


def test_tout_champ_de_montant_connu_est_couvert() -> None:
    """Un champ financier ajouté plus tard sans être listé fuiterait en silence."""
    assert {"fees_expected", "fees_paid", "fees_remaining", "fees_rate", "fees_balance"} == set(
        AMOUNT_FIELDS
    )


# ---------------------------------------------------------------------------
# La matrice
# ---------------------------------------------------------------------------


def test_la_permission_d_etat_existe() -> None:
    assert "payments:status:read" in {p["slug"] for p in ALL_PERMISSIONS}


def test_seuls_ceux_qui_manipulent_l_argent_voient_les_montants() -> None:
    for role in ("admin", "director", "accountant", "cashier", "staff"):
        assert "payments:read" in _perms(role), f"{role} encaisse ou arbitre : il voit"

    for role in ("educator", "studies_director", "teacher", "parent", "student"):
        assert "payments:read" not in _perms(role), f"{role} ne doit pas voir les montants"


def test_educateur_et_directeur_des_etudes_gardent_l_etat() -> None:
    """L'éducateur valide une inscription sur constat d'encaissement, sans
    jamais apprendre combien la famille doit."""
    for role in ("educator", "studies_director"):
        assert "payments:status:read" in _perms(role)


def test_l_enseignant_ne_voit_ni_montant_ni_etat() -> None:
    perms = _perms("teacher")
    assert "payments:read" not in perms
    assert "payments:status:read" not in perms


def test_le_secretariat_garde_sa_caisse_pas_la_tresorerie() -> None:
    """Il est caissier quand il encaisse, pas trésorier."""
    perms = _perms("staff")
    assert "payments:create" in perms
    assert "cash-session:manage" in perms
    assert "payments:read:all" not in perms, "les encaissements des autres ne le regardent pas"
    assert "cash-session:read:all" not in perms

    accountant = _perms("accountant")
    assert "payments:read:all" in accountant, "la vue consolidée reste au comptable"
    assert "cash-session:read:all" in accountant


# ---------------------------------------------------------------------------
# Le comptable configure la grille tarifaire de bout en bout
# ---------------------------------------------------------------------------


def test_le_comptable_configure_frais_et_tranches_de_bout_en_bout() -> None:
    """Il crée, modifie et supprime : une grille qu'on ne peut que lire ne
    sert à rien quand les tarifs changent en cours d'année."""
    perms = _perms("accountant")
    for entity in ("fee-categories", "fee-variants", "fee-options"):
        for verb in ("read", "create", "update", "delete"):
            assert f"admin:{entity}:{verb}" in perms, f"admin:{entity}:{verb} manque"
    assert "admin:fee-installments:read" in perms
    assert "admin:fee-installments:write" in perms


def test_le_comptable_gere_niveaux_et_series() -> None:
    """La grille se décline par niveau et par série : sans le droit de créer
    le niveau qui manque, il reste bloqué au milieu de sa configuration."""
    perms = _perms("accountant")
    for verb in ("read", "create", "update", "delete"):
        assert f"admin:levels:{verb}" in perms
    assert "admin:series:read" in perms
    assert "admin:series:write" in perms


def test_aucun_role_ne_reference_un_slug_inexistant() -> None:
    """Un slug référencé mais jamais installé donne un 403 silencieux : la
    page se charge, l'action échoue, et personne ne comprend pourquoi."""
    catalogue = {p["slug"] for p in ALL_PERMISSIONS}
    for role, definition in ROLE_DEFINITIONS.items():
        unknown = set(definition["permissions"]) - catalogue
        assert not unknown, f"{role} référence des slugs absents du catalogue : {unknown}"
