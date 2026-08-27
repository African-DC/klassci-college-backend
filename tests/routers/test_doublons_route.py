"""La route, appelée comme le frontend l'appelle.

Trente-trois tests passaient par `chercher_doublons` en direct, aucun ne
traversait le routeur. Une passe de revue a donc pu remplacer l'appel par
`duplicates.reponse_doublons`, un nom que le paquet n'exporte pas : l'import
réussissait, l'application démarrait, le test d'ordre des routes restait vert,
et **chaque frappe du formulaire rendait 500**. Le trou était exactement là où
le câblage se fait.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.routers import duplicates as routeur_doublons
from app.schemas.duplicates import DoublonsResponse

CHEMIN = "/admin/students/doublons"


def test_la_route_repond_200(client: TestClient) -> None:
    """Le câblage complet : URL, permission, sérialisation."""
    with patch.object(
        routeur_doublons,
        "chercher_doublons",
        new_callable=AsyncMock,
        return_value=DoublonsResponse(correspondances=[], tronque=False),
    ) as service:
        reponse = client.get(CHEMIN, params={"last_name": "KOUASSI", "first_name": "Aya"})

    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == {"correspondances": [], "tronque": False}
    service.assert_awaited_once()


def test_les_criteres_saisis_parviennent_au_service(client: TestClient) -> None:
    """Un paramètre perdu en route rendrait 200 sur une recherche vide."""
    with patch.object(
        routeur_doublons,
        "chercher_doublons",
        new_callable=AsyncMock,
        return_value=DoublonsResponse(correspondances=[], tronque=False),
    ) as service:
        client.get(
            CHEMIN,
            params={
                "last_name": "COULIBALY",
                "first_name": "Souleymane",
                "birth_date": "2010-03-14",
                "enrollment_number": "ECER0734",
                "academic_year_id": 7,
                "ignorer_student_id": 3,
            },
        )

    recus = service.await_args.kwargs
    assert recus["last_name"] == "COULIBALY"
    assert recus["first_name"] == "Souleymane"
    assert str(recus["birth_date"]) == "2010-03-14"
    assert recus["enrollment_number"] == "ECER0734"
    assert recus["academic_year_id"] == 7
    assert recus["ignorer_student_id"] == 3


@pytest.mark.parametrize("valeur", ["doublons", "abc"])
def test_le_segment_litteral_ne_part_pas_dans_la_route_parametrique(
    client: TestClient, valeur: str
) -> None:
    """`/students/doublons` ne doit pas tenter `int("doublons")`.

    Sans l'ordre de montage, FastAPI essaie `/students/{student_id}` et rend
    422 à chaque frappe.
    """
    with patch.object(
        routeur_doublons,
        "chercher_doublons",
        new_callable=AsyncMock,
        return_value=DoublonsResponse(correspondances=[], tronque=False),
    ):
        reponse = client.get(f"/admin/students/{valeur}", params={"last_name": "KOUASSI"})

    if valeur == "doublons":
        assert reponse.status_code == 200
    else:
        assert reponse.status_code == 422


def test_la_route_refuse_sans_le_droit_de_lire_les_eleves(client: TestClient) -> None:
    """La permission n'était gardée par rien.

    L'endpoint rend le nom, le prénom, le matricule et la date de naissance de
    mineurs. Supprimer `require_permission` laissait la suite entière verte : un
    garde que rien ne teste est un garde que la prochaine refonte enlève.

    On coupe la résolution des droits au niveau où elle décide, pas au niveau du
    routeur, pour que le test suive si le câblage change.
    """
    with patch(
        "app.core.dependencies._resolve_permission",
        new_callable=AsyncMock,
        return_value=False,
    ):
        reponse = client.get(CHEMIN, params={"last_name": "KOUASSI", "first_name": "Aya"})

    assert reponse.status_code == 403, reponse.text
    assert "admin:students:read" in reponse.text
