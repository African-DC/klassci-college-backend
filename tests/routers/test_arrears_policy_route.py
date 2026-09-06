"""L'écran de la politique de dettes demande un droit, et lequel.

Aucun domaine `settings:*` n'a été créé pour cet écran : un domaine à un membre
n'en est pas un, et il n'existerait sur aucune école déjà ouverte sans une
seconde migration pour le semer. L'écran est donc gardé par
`admin:fee-categories:*` — le droit « je fixe les règles d'argent de cette
école », porté par `admin` et `director` seulement.

Ce test coupe la résolution des droits là où elle décide, pas au niveau du
routeur, pour qu'il suive si le câblage change. Un garde que rien ne teste est
un garde que la prochaine refonte enlève.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.tenants.permissions import ALL_PERMISSIONS, ROLE_DEFINITIONS

CHEMIN = "/admin/arrears-policy"

_CORPS = {"arrears_policy": "block", "arrears_block_threshold_xof": 50000}


def test_lecture_refusee_sans_le_droit(client: TestClient) -> None:
    with patch(
        "app.core.dependencies.resolve_permission",
        new_callable=AsyncMock,
        return_value=False,
    ):
        reponse = client.get(CHEMIN)

    assert reponse.status_code == 403, reponse.text
    assert "admin:fee-categories:read" in reponse.text


def test_reglage_refuse_sans_le_droit_de_fixer_les_regles_dargent(client: TestClient) -> None:
    with patch(
        "app.core.dependencies.resolve_permission",
        new_callable=AsyncMock,
        return_value=False,
    ):
        reponse = client.put(CHEMIN, json=_CORPS)

    assert reponse.status_code == 403, reponse.text
    assert "admin:fee-categories:update" in reponse.text


@pytest.mark.parametrize(
    "corps",
    [
        {"arrears_policy": "block"},
        {"arrears_block_threshold_xof": 50000},
        {"arrears_policy": "block", "arrears_block_threshold_xof": -1},
        {"arrears_policy": "parfois", "arrears_block_threshold_xof": 0},
    ],
    ids=["seuil absent", "politique absente", "seuil negatif", "politique inconnue"],
)
def test_un_corps_incomplet_ou_faux_nentre_pas(client: TestClient, corps: dict[str, Any]) -> None:
    """Le réglage s'énonce entier : un champ manquant est un 422, pas une écriture à moitié."""
    with (
        patch(
            "app.core.dependencies.resolve_permission",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.services.arrears_policy.update_settings",
            new_callable=AsyncMock,
        ) as ecriture,
    ):
        reponse = client.put(CHEMIN, json=corps)

    assert reponse.status_code == 422, reponse.text
    ecriture.assert_not_awaited()


def test_le_droit_demande_existe_au_catalogue() -> None:
    """Un slug absent du catalogue serait un écran que personne ne peut ouvrir.

    Le domaine n'est pas créé pour l'occasion : il existe, donc il est déjà semé
    sur toutes les écoles ouvertes. C'est précisément ce qu'un `settings:*` à un
    membre n'aurait pas été.
    """
    catalogue = {p["slug"] for p in ALL_PERMISSIONS}
    for slug in ("admin:fee-categories:read", "admin:fee-categories:update"):
        assert slug in catalogue


def test_seul_le_public_des_regles_dargent_peut_fixer_la_politique() -> None:
    """Qui fixe les tarifs fixe la règle de recouvrement — et personne d'autre.

    Le public par défaut est la direction plus le comptable : le même que celui
    de la grille des frais, ce qui est exactement l'intention. Chaque école
    reste libre de le restreindre depuis l'écran des rôles, la matrice étant
    lue en base.

    Ce test est un garde-fou : le jour où le domaine `admin:fee-categories:*`
    s'ouvre à un profil de plus, il tombe, et quelqu'un décide en connaissance
    de cause si ce profil doit aussi pouvoir bloquer une réinscription.
    """
    porteurs = {
        role
        for role, definition in ROLE_DEFINITIONS.items()
        if "admin:fee-categories:update" in set(definition["permissions"])
    }
    assert porteurs == {"admin", "director", "accountant"}
