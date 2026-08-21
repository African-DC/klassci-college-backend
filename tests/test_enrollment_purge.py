"""Supprimer une inscription obéit aux mêmes règles que supprimer un élève.

La suppression définitive d'une inscription empruntait son propre chemin. Ce
chemin ignorait le motif reçu, ne vérifiait pas que la fiche était bien passée
par la corbeille, n'écrivait ni le motif ni le libellé au journal, et ne
prévenait personne. Quatre promesses tenues pour l'élève, le parent,
l'enseignant et le personnel, rompues pour la seule inscription — celle qui
porte l'argent des familles.

Ces tests appellent le vrai service avec le vrai `ENROLLMENT_KIND`.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.exceptions import BusinessValidationError
from app.models.enrollment import EnrollmentStatus
from app.services import archive_service
from app.services.enrollment_archive import ENROLLMENT_KIND

MOTIF = "Inscription saisie deux fois le 12 aout"


class _Resultat:
    """Une réponse de base qui sert les deux lectures du module.

    `_load_enrollment_for_bin` demande une inscription, `_count_payments` un
    nombre : chacun appelle la méthode qui lui correspond.
    """

    def __init__(self, inscription: object, versements: int) -> None:
        self._inscription = inscription
        self._versements = versements

    def scalar_one_or_none(self) -> object:
        return self._inscription

    def scalar(self) -> int:
        return self._versements


class _Session:
    """Juste ce qu'il faut de session pour dérouler les gestes de corbeille."""

    def __init__(self, inscription: object, versements: int = 0) -> None:
        self._resultat = _Resultat(inscription, versements)
        self.detruits: list[object] = []
        self.commits = 0

    async def execute(self, _statement: object) -> _Resultat:
        return self._resultat

    async def delete(self, instance: object) -> None:
        self.detruits.append(instance)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    def begin_nested(self):  # noqa: ANN201 - contexte asynchrone minimal
        class _Nested:
            async def __aenter__(self_inner) -> None:
                return None

            async def __aexit__(self_inner, *_exc: object) -> bool:
                return False

        return _Nested()


def _inscription(*, archivee: bool, statut: str = EnrollmentStatus.VALIDE) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        status=statut,
        archived_at="2026-08-20" if archivee else None,
        archived_by=1 if archivee else None,
        archive_reason=MOTIF if archivee else None,
        student=SimpleNamespace(first_name="Aminata", last_name="Traoré"),
    )


@pytest.fixture
def journal(monkeypatch: pytest.MonkeyPatch) -> tuple[list[dict], list[object]]:
    """Retient ce qui part au journal d'audit et ce qui part par courriel."""
    ecrit: list[dict] = []
    envoye: list[object] = []

    async def _audit(_db: object, **kwargs: object) -> None:
        ecrit.append(kwargs)

    async def _notify(_db: object, outcome: object) -> None:
        envoye.append(outcome)

    monkeypatch.setattr(archive_service, "audit_log", _audit)
    monkeypatch.setattr(archive_service, "notify", _notify)
    return ecrit, envoye


# ---------------------------------------------------------------------------
# Le motif
# ---------------------------------------------------------------------------


async def test_supprimer_une_inscription_sans_motif_est_refuse(
    journal: tuple[list[dict], list[object]],
) -> None:
    """Le motif reçu n'était jamais lu : on pouvait supprimer sans rien dire."""
    db = _Session(_inscription(archivee=True))

    for absent in (None, "", "ok"):
        with pytest.raises(HTTPException) as exc:
            await archive_service.purge_record(
                db,  # type: ignore[arg-type]
                ENROLLMENT_KIND,
                42,
                reason=absent,
                actor_id=1,
            )
        assert exc.value.status_code == 422

    assert db.detruits == [], "rien ne doit être détruit sans motif"


# ---------------------------------------------------------------------------
# L'ordre des gestes
# ---------------------------------------------------------------------------


async def test_une_inscription_encore_visible_ne_se_supprime_pas(
    journal: tuple[list[dict], list[object]],
) -> None:
    """Le passage par la corbeille est ce qui laisse le temps de se raviser."""
    db = _Session(_inscription(archivee=False, statut=EnrollmentStatus.PROSPECT))

    with pytest.raises(HTTPException) as exc:
        await archive_service.purge_record(
            db,  # type: ignore[arg-type]
            ENROLLMENT_KIND,
            42,
            reason=MOTIF,
            actor_id=1,
        )

    assert exc.value.status_code == 409
    assert "corbeille" in exc.value.detail
    assert db.detruits == []


# ---------------------------------------------------------------------------
# La trace
# ---------------------------------------------------------------------------


async def test_la_suppression_ecrit_le_motif_et_le_nom_au_journal(
    journal: tuple[list[dict], list[object]],
) -> None:
    """« L'inscription 42 a été supprimée » ne dit ni de qui ni pourquoi."""
    ecrit, _envoye = journal
    inscription = _inscription(archivee=True)
    db = _Session(inscription)

    await archive_service.purge_record(
        db,  # type: ignore[arg-type]
        ENROLLMENT_KIND,
        42,
        reason=MOTIF,
        actor_id=7,
    )

    assert db.detruits == [inscription]
    assert len(ecrit) == 1
    entree = ecrit[0]
    assert entree["entity_type"] == "enrollment"
    assert entree["entity_id"] == 42
    assert entree["user_id"] == 7
    assert entree["notes"] == MOTIF
    assert entree["old_values"] == {"label": "L'inscription de Traoré Aminata"}
    assert entree["new_values"]["permanent"] is True


async def test_la_suppression_previent_la_direction(
    journal: tuple[list[dict], list[object]],
) -> None:
    """Un mail sort du logiciel : qui efface une trace n'efface pas une boîte
    de réception."""
    _ecrit, envoye = journal
    db = _Session(_inscription(archivee=True))

    await archive_service.purge_record(
        db,  # type: ignore[arg-type]
        ENROLLMENT_KIND,
        42,
        reason=MOTIF,
        actor_id=1,
    )

    assert len(envoye) == 1
    assert envoye[0].permanent is True
    assert envoye[0].entity_type == "enrollment"
    assert envoye[0].reason == MOTIF
    assert envoye[0].label == "L'inscription de Traoré Aminata"


# ---------------------------------------------------------------------------
# L'argent
# ---------------------------------------------------------------------------


async def test_une_inscription_qui_porte_des_versements_ne_se_supprime_pas(
    journal: tuple[list[dict], list[object]],
) -> None:
    """Le versement perdrait sa contrepartie, et le journal d'audit ne
    rattrape pas un trou comptable."""
    db = _Session(_inscription(archivee=True), versements=3)

    with pytest.raises(BusinessValidationError) as exc:
        await archive_service.purge_record(
            db,  # type: ignore[arg-type]
            ENROLLMENT_KIND,
            42,
            reason=MOTIF,
            actor_id=1,
        )

    assert "versements" in str(exc.value)
    assert db.detruits == []


async def test_une_inscription_validee_deja_encaissee_ne_part_pas_a_la_corbeille(
    journal: tuple[list[dict], list[object]],
) -> None:
    """Archiver masque la fiche des écrans de la caisse : le bordereau du jour
    se mettrait à mentir."""
    inscription = _inscription(archivee=False)
    db = _Session(inscription, versements=1)

    with pytest.raises(BusinessValidationError):
        await archive_service.archive_record(
            db,  # type: ignore[arg-type]
            ENROLLMENT_KIND,
            42,
            reason=MOTIF,
            actor_id=1,
        )

    assert inscription.archived_at is None


async def test_un_prospect_sans_versement_part_a_la_corbeille(
    journal: tuple[list[dict], list[object]],
) -> None:
    """La fiche que le secrétariat range vraiment : un dossier abandonné."""
    inscription = _inscription(archivee=False, statut=EnrollmentStatus.PROSPECT)
    db = _Session(inscription)

    await archive_service.archive_record(
        db,  # type: ignore[arg-type]
        ENROLLMENT_KIND,
        42,
        reason=MOTIF,
        actor_id=1,
    )

    assert inscription.archived_at is not None
    assert inscription.archive_reason == MOTIF


# ---------------------------------------------------------------------------
# Le garde vit dans le type, pas dans un second chemin
# ---------------------------------------------------------------------------


def test_le_service_d_inscription_n_expose_plus_de_suppression_a_part() -> None:
    """La fonction supprimée ne doit pas revenir par la fenêtre."""
    from app.services import enrollment_archive

    assert not hasattr(enrollment_archive, "delete_enrollment")


def test_le_motif_ne_voyage_plus_dans_l_url() -> None:
    """Une URL finit dans les journaux d'accès du serveur et chez les
    intermédiaires : « exclu pour vol » n'a rien à y faire."""
    from app.main import app

    routes = [
        r
        for r in app.routes
        if getattr(r, "path", None) == "/enrollments/{enrollment_id}"
        and "DELETE" in getattr(r, "methods", set())
    ]
    assert len(routes) == 1
    noms = {p.name for p in routes[0].dependant.query_params}
    assert "reason" not in noms
    assert routes[0].body_field is not None, "le motif doit voyager dans le corps"
