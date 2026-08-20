"""Journal d'audit — cloisonnement, identité figée, périmètre des consultations."""

import pytest

from app.core.audit import Actor, AuditAction, current_actor
from app.services.audit._scope import FINANCIAL_ENTITIES, visible_entity_types
from app.services.tenants.permissions import ALL_PERMISSIONS, ROLE_DEFINITIONS

# ---------------------------------------------------------------------------
# Qui voit quoi
# ---------------------------------------------------------------------------


def test_direction_voit_tout_le_journal() -> None:
    assert visible_entity_types(full_access=True, financial_access=False) is None


def test_acces_complet_prime_sur_la_vue_financiere() -> None:
    """Un directeur qui a aussi la vue financière ne doit pas s'y trouver enfermé."""
    assert visible_entity_types(full_access=True, financial_access=True) is None


def test_comptable_voit_l_argent_et_rien_d_autre() -> None:
    allowed = visible_entity_types(full_access=False, financial_access=True)
    assert allowed == FINANCIAL_ENTITIES
    assert "payment" in allowed
    # Remonter un versement contesté n'exige pas de lire les notes ni les
    # décisions de conseil au passage.
    for hors_perimetre in ("grade", "bulletin", "council_student_decision", "staff", "student"):
        assert hors_perimetre not in allowed


def test_sans_droit_rien_n_est_visible() -> None:
    assert visible_entity_types(full_access=False, financial_access=False) == frozenset()


def test_matrice_des_roles() -> None:
    slugs = {p["slug"] for p in ALL_PERMISSIONS}
    assert {"audit:read", "audit:read:financial"} <= slugs

    def perms(role: str) -> set[str]:
        return set(ROLE_DEFINITIONS[role]["permissions"])

    assert "audit:read" in perms("admin")
    assert "audit:read" in perms("director")
    assert "audit:read:financial" in perms("accountant")
    assert "audit:read" not in perms("accountant"), "le comptable n'a pas le journal complet"

    # Le secrétariat partage le groupe caisse du comptable : vérifier qu'il n'a
    # pas hérité du journal financier au passage.
    for role in (
        "staff",
        "cashier",
        "educator",
        "studies_director",
        "teacher",
        "parent",
        "student",
    ):
        assert "audit:read" not in perms(role)
        assert "audit:read:financial" not in perms(role), f"{role} ne lit pas le journal financier"


# ---------------------------------------------------------------------------
# Identité figée
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_actor():
    token = current_actor.set(None)
    yield
    current_actor.reset(token)


def test_l_identite_est_recopiee_pour_l_auteur_courant() -> None:
    from app.core import audit

    current_actor.set(Actor(user_id=7, email="sophie@ecole.ci", role="staff"))
    actor = audit.current_actor.get()
    assert actor is not None
    assert actor.email == "sophie@ecole.ci"


def test_la_consultation_est_une_action_a_part_entiere() -> None:
    """`read` doit exister pour distinguer « a regardé » de « a modifié »."""
    assert AuditAction.READ.value == "read"
    assert AuditAction.READ not in {
        AuditAction.CREATE,
        AuditAction.UPDATE,
        AuditAction.DELETE,
    }


def test_le_role_est_ecrit_en_slug_pas_en_repr_python() -> None:
    """`str(User.role)` donnerait « UserRoleEnum.ADMIN », illisible et intraduisible."""
    from app.core.dependencies import _role_value
    from app.models.user import UserRoleEnum

    assert _role_value(UserRoleEnum.ADMIN) == "admin"
    assert _role_value("accountant") == "accountant"
