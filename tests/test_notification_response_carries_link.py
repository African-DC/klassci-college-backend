"""Le lien de la notification doit sortir du serveur.

La colonne `action_url` existait, le service l'écrivait, et le schéma de
réponse ne la mentionnait pas : le lien était posé, jamais livré. Rien ne
signalait ce trou — le code compilait, les tests passaient, la colonne se
remplissait bien. Seul un client qui cherche le champ s'en aperçoit.

Ce test lit la réponse telle qu'elle part, pas le modèle.
"""

from datetime import UTC, datetime

from app.schemas.notification import NotificationResponse


def _ligne(**extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": 1,
        "user_id": 7,
        "type": "enrollment_awaiting_payment",
        "channel": "in_app",
        "title": "Versement attendu",
        "body": "Traoré Aminata (6ème A) vient d'être inscrit.",
        "read": False,
        "sent_at": datetime.now(UTC),
        "read_at": None,
        "entity_type": "enrollment",
        "entity_id": 42,
        "created_at": datetime.now(UTC),
    }
    base.update(extra)
    return base


def test_la_reponse_porte_le_lien() -> None:
    reponse = NotificationResponse(**_ligne(action_url="/admin/enrollments/42?action=encaisser"))
    rendu = reponse.model_dump()
    assert "action_url" in rendu
    assert rendu["action_url"] == "/admin/enrollments/42?action=encaisser"


def test_une_notification_sans_lien_reste_valide() -> None:
    # Les notifications anterieures a la colonne n'en ont pas : elles doivent
    # continuer de s'afficher, simplement sans destination.
    reponse = NotificationResponse(**_ligne())
    assert reponse.model_dump()["action_url"] is None
