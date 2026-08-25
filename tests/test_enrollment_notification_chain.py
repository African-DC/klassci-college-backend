"""La chaîne inscription → encaissement → validation prévient les bonnes personnes.

Trois gestes, trois personnes possibles. Sans lien entre eux, chaque geste
attend que quelqu'un pense à regarder — et dans une école, personne ne
regarde : on est au guichet, en classe, ou au téléphone.

Ces tests exercent la diffusion réelle, avec un dépôt de permissions doublé.
Ils ne lisent pas le code : ils vérifient qui figure dans la liste des
destinataires, et qui n'y figure pas.
"""

from typing import Any

import pytest

from app.services import enrollment_notifications, notification_dispatch_service

SECRETAIRE = 1
DIRECTEUR = 3
CAISSIER_SANS_DROIT = 2


@pytest.fixture()
def envois(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture ce que la diffusion aurait écrit, sans base ni gabarit."""
    captures: list[dict[str, Any]] = []

    async def _faux_dispatch(db, user_id, notification_type, context, channels=None, **kw):
        captures.append(
            {
                "user_id": user_id,
                "type": notification_type,
                "action_url": kw.get("action_url"),
                "entity_id": kw.get("entity_id"),
                "title": context.get("title"),
            }
        )
        return object()

    async def _faux_resolveur(db, slug):
        return {
            "payments:create": [SECRETAIRE, DIRECTEUR],
            "enrollments:validate": [DIRECTEUR],
        }.get(slug, [])

    monkeypatch.setattr(notification_dispatch_service, "dispatch_notification", _faux_dispatch)
    monkeypatch.setattr(
        notification_dispatch_service.permission_repository,
        "list_user_ids_with_permission",
        _faux_resolveur,
    )
    return captures


@pytest.mark.asyncio
async def test_une_inscription_creee_previent_qui_peut_encaisser(envois) -> None:
    await enrollment_notifications.prevenir_qu_il_faut_encaisser(
        None, enrollment_id=42, student_name="Traoré Aminata", class_name="6ème A", acteur_id=None
    )
    assert sorted(e["user_id"] for e in envois) == [SECRETAIRE, DIRECTEUR]
    # Le « caissier » sans le droit n'est pas prévenu : c'est la permission
    # qui désigne, jamais le nom qu'on donne à quelqu'un.
    assert CAISSIER_SANS_DROIT not in [e["user_id"] for e in envois]


@pytest.mark.asyncio
async def test_ne_previent_pas_celui_qui_vient_d_agir(envois) -> None:
    await enrollment_notifications.prevenir_qu_il_faut_encaisser(
        None,
        enrollment_id=42,
        student_name="Traoré Aminata",
        class_name="6ème A",
        acteur_id=SECRETAIRE,
    )
    # Être averti de sa propre action n'apprend rien et use le compteur.
    assert [e["user_id"] for e in envois] == [DIRECTEUR]


@pytest.mark.asyncio
async def test_le_versement_previent_qui_peut_valider(envois) -> None:
    await enrollment_notifications.prevenir_qu_il_faut_valider(
        None, enrollment_id=42, student_name="Traoré Aminata", acteur_id=None
    )
    assert [e["user_id"] for e in envois] == [DIRECTEUR]
    assert envois[0]["title"] == "Inscription à valider"


@pytest.mark.asyncio
async def test_chaque_notification_mene_a_l_ecran_ou_l_on_agit(envois) -> None:
    await enrollment_notifications.prevenir_qu_il_faut_encaisser(
        None, enrollment_id=42, student_name="X", class_name="6ème A", acteur_id=None
    )
    await enrollment_notifications.prevenir_qu_il_faut_valider(
        None, enrollment_id=42, student_name="X", acteur_id=None
    )
    liens = [e["action_url"] for e in envois]
    # Le lien porte l'action attendue, pas seulement la fiche : on arrive là
    # où l'on fait la chose, pas là où on la contemple.
    assert all(lien and "/admin/enrollments/42" in lien for lien in liens)
    assert any("encaisser" in lien for lien in liens)
    assert any("valider" in lien for lien in liens)


@pytest.mark.asyncio
async def test_une_cloche_en_panne_n_empeche_pas_d_inscrire(monkeypatch) -> None:
    async def _explose(*a, **kw):
        raise RuntimeError("service de notification indisponible")

    monkeypatch.setattr(notification_dispatch_service, "dispatch_to_permission", _explose)
    # Ne doit pas lever : prévenir est un effet de l'inscription, jamais sa
    # condition. Un enfant s'inscrit même si la notification échoue.
    await enrollment_notifications.prevenir_qu_il_faut_encaisser(
        None, enrollment_id=42, student_name="X", class_name="6ème A", acteur_id=None
    )
