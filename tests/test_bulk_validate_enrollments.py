"""Valider une cohorte sans que le lot s'arrête à la troisième ligne.

Une école valide une promotion entière à la rentrée. Dossier par dossier,
c'est l'après-midi — et rien dans le geste ne le justifie : la décision a été
prise en conseil, l'écran ne fait que l'enregistrer.

Ce qui compte ici n'est pas la boucle, c'est ce qui arrive quand une ligne
refuse. Un lot qui s'interrompt laisse le secrétariat sans savoir ce qui est
passé, et l'oblige à tout reprendre pour le découvrir.
"""

import pytest

from app.core.exceptions import BusinessValidationError, NotFoundError
from app.services import enrollment_service


@pytest.fixture()
def validations(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Remplace la validation unitaire : ici on teste l'orchestration."""
    faites: list[int] = []

    async def _valider(db, enrollment_id, validated_by):
        if enrollment_id == 2:
            raise BusinessValidationError("Cette inscription est déjà validée.")
        if enrollment_id == 3:
            raise NotFoundError("Enrollment", 3)
        faites.append(enrollment_id)
        return object()

    monkeypatch.setattr(enrollment_service, "validate_enrollment", _valider)
    return faites


@pytest.mark.asyncio
async def test_un_echec_n_arrete_pas_le_lot(validations) -> None:
    res = await enrollment_service.validate_enrollments_in_bulk(None, [1, 2, 3, 4], validated_by=9)
    # La 4 est validée bien qu'elle vienne après deux échecs.
    assert res["validated"] == [1, 4]
    assert validations == [1, 4]


@pytest.mark.asyncio
async def test_chaque_echec_dit_pourquoi(validations) -> None:
    res = await enrollment_service.validate_enrollments_in_bulk(None, [1, 2, 3], validated_by=9)
    motifs = {e["enrollment_id"]: e["reason"] for e in res["failed"]}
    assert set(motifs) == {2, 3}
    # Sans le motif, l'écran ne peut que dire « certaines ont échoué », ce qui
    # oblige à rouvrir chaque dossier pour comprendre.
    assert "déjà validée" in motifs[2]
    assert motifs[3]


@pytest.mark.asyncio
async def test_un_lot_entierement_valide_ne_rapporte_aucun_echec(validations) -> None:
    res = await enrollment_service.validate_enrollments_in_bulk(None, [1, 4, 5], validated_by=9)
    assert res["validated"] == [1, 4, 5]
    assert res["failed"] == []


@pytest.mark.asyncio
async def test_un_lot_entierement_en_echec_ne_valide_rien(validations) -> None:
    res = await enrollment_service.validate_enrollments_in_bulk(None, [2, 3], validated_by=9)
    assert res["validated"] == []
    assert len(res["failed"]) == 2
