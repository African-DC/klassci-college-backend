"""La chaîne inscription → encaissement → validation prévient les bonnes personnes.

Trois gestes, trois personnes possibles. Sans lien entre eux, chaque geste
attend que quelqu'un pense à regarder — et dans une école, personne ne
regarde : on est au guichet, en classe, ou au téléphone.

Ces tests exercent la diffusion réelle, avec un dépôt de permissions doublé.
Ils ne lisent pas le code : ils vérifient qui figure dans la liste des
destinataires, et qui n'y figure pas.
"""

from decimal import Decimal
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
                "body": context.get("body"),
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
    monkeypatch.setattr(
        enrollment_notifications.permission_repository,
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


INSCRIPTEUR_SANS_DROIT = 5


async def _versement(acteur_id: int | None = None, createur_id: int | None = None) -> None:
    await enrollment_notifications.prevenir_du_versement(
        None,
        enrollment_id=42,
        student_name="Traoré Aminata",
        montant=Decimal("25000"),
        moyen="cash",
        reste=Decimal("30000"),
        createur_id=createur_id,
        acteur_id=acteur_id,
    )


@pytest.mark.asyncio
async def test_le_versement_previent_qui_peut_valider(envois) -> None:
    await _versement()
    assert [e["user_id"] for e in envois] == [DIRECTEUR]
    assert envois[0]["title"] == "Versement reçu, inscription à valider"


@pytest.mark.asyncio
async def test_le_versement_previent_celui_qui_a_ouvert_le_dossier(envois) -> None:
    """Il n'a ni le droit de valider ni celui de voir les paiements, et il est
    prévenu quand même : c'est lui qui attend ce versement pour avancer."""
    await _versement(createur_id=INSCRIPTEUR_SANS_DROIT)
    assert sorted(e["user_id"] for e in envois) == [DIRECTEUR, INSCRIPTEUR_SANS_DROIT]


@pytest.mark.asyncio
async def test_le_message_dit_le_montant_et_le_reste_sans_ouvrir_les_paiements(envois) -> None:
    await _versement(createur_id=INSCRIPTEUR_SANS_DROIT)
    corps = envois[0]["body"]
    assert "25 000 FCFA" in corps
    assert "Espèces" in corps
    assert "Reste à payer : 30 000 FCFA" in corps


@pytest.mark.asyncio
async def test_le_createur_qui_peut_valider_n_est_prevenu_qu_une_fois(envois) -> None:
    await _versement(createur_id=DIRECTEUR)
    assert [e["user_id"] for e in envois] == [DIRECTEUR]


@pytest.mark.asyncio
async def test_la_caissiere_ne_se_previent_pas_elle_meme(envois) -> None:
    await _versement(createur_id=SECRETAIRE, acteur_id=SECRETAIRE)
    assert [e["user_id"] for e in envois] == [DIRECTEUR]


@pytest.mark.asyncio
async def test_chaque_notification_mene_a_l_ecran_ou_l_on_agit(envois) -> None:
    await enrollment_notifications.prevenir_qu_il_faut_encaisser(
        None, enrollment_id=42, student_name="X", class_name="6ème A", acteur_id=None
    )
    await _versement()
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
