"""Une somme versée ne peut pas valoir trois montants selon l'écran."""

from app.services import fees_paid


def test_le_calcul_vit_a_un_seul_endroit() -> None:
    """Trois services calculaient « déjà payé » de trois façons. Le portail
    parent et le portail élève sommaient une relation dépréciée depuis la
    migration 0028 et sous-estimaient donc ce que la famille avait versé —
    50 000 FCFA invisibles sur un cas réel du tenant de démonstration."""
    assert hasattr(fees_paid, "paid_by_enrollment_fee")
    assert hasattr(fees_paid, "paid_by_enrollment")


def test_les_portails_ne_somment_plus_la_relation_depreciee() -> None:
    """`EnrollmentFee.payments` s'appuie sur `Payment.enrollment_fee_id`, vide
    sur tout versement passé par les allocations."""
    from pathlib import Path

    for module in ("parent_portal_service", "student_portal_service"):
        source = Path(f"app/services/{module}.py").read_text(encoding="utf-8")
        fautives = [
            ligne.strip()
            for ligne in source.splitlines()
            if "ef.payments" in ligne and "total_paid" in ligne
        ]
        assert not fautives, f"{module} somme encore la relation dépréciée : {fautives}"
        assert "fees_paid" in source, f"{module} doit passer par le calcul canonique"
