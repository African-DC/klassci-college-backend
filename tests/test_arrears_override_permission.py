"""Le droit de passer outre un blocage pour dette existe dans les DEUX sources.

Un établissement neuf reçoit ses droits du catalogue
(`app/services/tenants/permissions.py`), une école déjà ouverte les reçoit de
la migration : `_seed_permissions_and_roles` ne joue qu'au provisionnement. Si
les deux divergent, la moitié du parc n'aura jamais le slug — donc personne
pour déroger le jour où le blocage arrive, et pour seule issue la désactivation
de la politique entière.
"""

from importlib import util as import_util
from pathlib import Path
from types import ModuleType

from app.services.tenants.permissions import ALL_PERMISSIONS, ROLE_DEFINITIONS

_SLUG = "enrollments:arrears:override"


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260906_0080_enrollment_arrears_override_perm.py"
    )
    spec = import_util.spec_from_file_location("migration_0080", path)
    assert spec is not None and spec.loader is not None
    module = import_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_le_slug_est_au_catalogue() -> None:
    """Sans lui, un tenant provisionné demain n'aurait pas la permission."""
    assert _SLUG in {p["slug"] for p in ALL_PERMISSIONS}


def test_la_migration_seme_le_meme_slug_que_le_catalogue() -> None:
    """Deux orthographes du même droit feraient deux droits, dont un mort."""
    assert _migration()._SLUG == _SLUG


def test_la_derogation_est_reservee_a_la_direction() -> None:
    """Celui qui constate la dette ne doit pas être celui qui l'efface."""
    allowed = {"admin", "director"}
    for role, definition in ROLE_DEFINITIONS.items():
        has = _SLUG in set(definition["permissions"])
        assert has is (role in allowed), f"le rôle « {role} » ne devrait pas pouvoir déroger"


def test_le_public_de_la_migration_est_celui_du_catalogue() -> None:
    """La migration sème depuis un slug voisin : les deux publics doivent coïncider.

    Elle n'énumère aucun rôle — elle recopie ceux qui détiennent déjà
    `documents:release:override`. Le jour où ce droit voisin change de mains,
    ce test tombe avant que le parc ne se retrouve à deux vitesses.
    """
    source = _migration()._SOURCE_SLUG

    seeded = {r for r, d in ROLE_DEFINITIONS.items() if source in set(d["permissions"])}
    expected = {r for r, d in ROLE_DEFINITIONS.items() if _SLUG in set(d["permissions"])}
    assert seeded == expected


def test_deroger_pour_un_document_n_inscrit_pas_un_debiteur() -> None:
    """Deux gestes, deux droits : les confondre donnerait l'un avec l'autre."""
    assert _migration()._SOURCE_SLUG != _SLUG
    assert "documents:release:override" in {p["slug"] for p in ALL_PERMISSIONS}
