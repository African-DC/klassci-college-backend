"""L'affectation corrigée sur la fiche doit s'écrire, et être écrite juste.

En Côte d'Ivoire, l'élève affecté par l'État dans un établissement privé est
subventionné : sa famille paie sensiblement moins. L'affectation décide donc
du tarif, exactement comme la classe ou le profil « nouvel élève ».

Deux pièges se tiennent ici, et ce sont eux que ces tests gardent.

Le premier est la sentinelle : `None` envoyé par le guichet veut dire « on
remet à non renseigné », pas « laisse tel quel ». Confondre les deux, c'est
soit refuser d'effacer une affectation posée par erreur, soit l'effacer à
chaque enregistrement de la fiche. Le journal d'audit doit d'ailleurs retenir
ce `null` : c'est le geste qui régénère toute la grille de frais, et sans lui
plus rien n'explique pourquoi la dette d'une famille a changé ce jour-là.

Le second est la valeur : le ministère n'en connaît que trois. Une quatrième
arrivée par une faute de frappe s'écrirait en base et se lirait ensuite comme
« non subventionné », donc en plein tarif, sur la facture d'une famille qui a
droit à la subvention.

Tests purement Pydantic : aucune base, aucun réseau.
"""

import pytest
from pydantic import ValidationError

from app.models.enrollment import AssignmentStatus
from app.schemas.enrollment import EnrollmentUpdate


def test_l_affectation_remise_a_vide_reste_dans_la_trace() -> None:
    """`None` est une valeur envoyée, pas un champ absent."""
    remise_a_zero = EnrollmentUpdate.model_validate({"assignment_status": None})

    assert "assignment_status" in remise_a_zero.model_fields_set
    trace = remise_a_zero.model_dump(include=remise_a_zero.model_fields_set, mode="json")
    assert trace == {"assignment_status": None}


def test_le_champ_absent_reste_absent() -> None:
    """Le journal dit ce que le guichet a envoyé, pas ce que le schéma porte."""
    autre_champ = EnrollmentUpdate.model_validate({"notes": "Dossier complété"})
    trace = autre_champ.model_dump(include=autre_champ.model_fields_set, mode="json")

    assert "assignment_status" not in trace
    assert "assignment_decision_number" not in trace


@pytest.mark.parametrize("statut", [s.value for s in AssignmentStatus])
def test_les_trois_statuts_du_ministere_passent(statut: str) -> None:
    """Ce que le schéma accepte suit l'énumération du modèle, sans dériver."""
    assert (
        EnrollmentUpdate.model_validate({"assignment_status": statut}).assignment_status == statut
    )


def test_un_statut_inconnu_est_refuse() -> None:
    """La faute de frappe est arrêtée au guichet, pas découverte sur la facture."""
    with pytest.raises(ValidationError):
        EnrollmentUpdate.model_validate({"assignment_status": "affecté"})


def test_le_numero_de_decision_voyage_avec_le_statut() -> None:
    """Les deux champs partent ensemble : la décision date l'affectation."""
    correction = EnrollmentUpdate.model_validate(
        {"assignment_status": "reaffecte", "assignment_decision_number": "2026-4417"}
    )
    trace = correction.model_dump(include=correction.model_fields_set, mode="json")

    assert trace == {"assignment_status": "reaffecte", "assignment_decision_number": "2026-4417"}
