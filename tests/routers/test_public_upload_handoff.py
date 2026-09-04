"""La route publique de dépôt : elle s'ouvre sans session, et n'écrit aucune fiche.

Ce que ces tests gardent
========================

1. **Elle n'écrit rien.** C'est la première route publique du projet qui pose
   un octet quelque part. Toute sa sûreté tient à ce que « quelque part » soit
   un sas, jamais une colonne : le dépôt attend le regard d'un opérateur
   authentifié. Si ce test tombe, ce n'est plus la même fonctionnalité.

2. **Elle ne révèle qu'un libellé pauvre.** Un code 2D se photographie dans un
   couloir. Le nom complet d'un mineur, son matricule ou sa classe sur cette
   page transformeraient une reprise de photo en divulgation.

3. **Un jeton ne dépose qu'une fois, et seulement dans son établissement.** Le
   code est affiché sur un écran, dans une salle : deux téléphones peuvent le
   scanner. Et une seule instance Redis sert toutes les écoles.

4. **Un échec rend la main.** La donnée mobile coupe au milieu d'un envoi : la
   session doit redevenir ouverte, sans consommer de reprise et sans qu'il
   faille rescanner quoi que ce soit.

5. **Elle est déclarée dans les trois listes codées en dur.** En oublier une
   donne un échec différent à chaque fois, et deux d'entre eux ne se voient pas
   en recette mono-établissement.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_tenant_db
from app.core.middleware import _GARDES_ENVOI_PUBLIC, _tenant_from_public_path
from app.core.redis import get_redis
from app.main import app
from app.services import upload_handoff_service as svc
from app.utils import handoff_storage
from tests.services.test_upload_handoff_service import FauxRedis

ECOLE = "rostan"
AUTRE_ECOLE = "wourri"
OPERATEUR = 7
JPEG = b"\xff\xd8\xff" + b"0" * 64
PDF = b"%PDF-1.7" + b"0" * 64
ROUTE = "/public/upload-handoff"


@pytest.fixture
def sas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    racine = tmp_path / "handoff"
    racine.mkdir()
    monkeypatch.setattr(handoff_storage, "HANDOFF_ROOT", racine)
    return racine


@pytest.fixture
def redis() -> FauxRedis:
    return FauxRedis()


@pytest.fixture
def db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def public_client(redis: FauxRedis, db: AsyncMock) -> Iterator[TestClient]:
    """Un client SANS identité : c'est tout l'intérêt de cette route.

    `get_current_user` n'est délibérément pas surchargé — s'il l'était, le test
    passerait aussi bien avec une route accidentellement protégée.

    Le quota d'envoi public est neutralisé : il vit dans le middleware, il a ses
    propres tests, et sans un vrai Redis il rendrait 503 sur chaque `POST`.
    """
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_tenant_db] = lambda: db
    quota = AsyncMock(return_value=None)
    with (
        patch("app.core.middleware._consume_public_upload_quota", quota),
        patch(
            "app.routers.public_upload_handoff.load_school_settings_for_pdf",
            new_callable=AsyncMock,
        ) as ecole,
    ):
        ecole.return_value = {"school_name": "Collège Rostan"}
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()


async def _ouvrir(redis: FauxRedis, *, tenant: str = ECOLE, **kwargs: Any) -> str:
    """Ouvre une session et rend le jeton en clair — celui du code 2D."""
    defauts: dict[str, Any] = {
        "target_kind": "student_photo",
        "owner_user_id": OPERATEUR,
        "label": "Kouadio A.",
        "subject_id": 42,
    }
    defauts.update(kwargs)
    _, token = await svc.open_session(redis, tenant=tenant, **defauts)
    return token


def _envoyer(client: TestClient, token: str, contenu: bytes, mime: str = "image/jpeg") -> Any:
    return client.post(
        f"{ROUTE}/{ECOLE}/{token}",
        files={"file": ("IMG_0042.jpg", contenu, mime)},
    )


# ---------------------------------------------------------------------------
# La propriété centrale : aucune fiche n'est touchée
# ---------------------------------------------------------------------------


async def test_un_depot_n_ecrit_aucune_fiche(
    public_client: TestClient, redis: FauxRedis, db: AsyncMock, sas: Path
) -> None:
    """Le téléphone dépose dans le sas et rien d'autre ne bouge.

    C'est ce qui rend acceptable qu'un jeton porteur circule dans un code que
    n'importe qui peut photographier : le pire qu'un code volé produit, c'est
    une image qu'un opérateur voit et refuse.
    """
    token = await _ouvrir(redis)

    reponse = _envoyer(public_client, token, JPEG)

    assert reponse.status_code == 200, reponse.text
    assert reponse.json()["state"] == "proposed"
    db.commit.assert_not_awaited()
    db.execute.assert_not_awaited()
    deposes = list(sas.iterdir())
    assert len(deposes) == 1
    assert deposes[0].read_bytes() == JPEG


async def test_le_depot_range_l_adresse_du_telephone(
    public_client: TestClient, redis: FauxRedis, sas: Path
) -> None:
    """Seule trace de qui a réellement pris la photo, journalisée à la confirmation.

    L'opérateur qui confirmera est identifié par sa propre session ; ce que
    cette adresse ajoute, c'est que l'image n'a pas été prise depuis son écran.
    """
    token = await _ouvrir(redis)

    _envoyer(public_client, token, JPEG)

    session = await svc.load_by_token(redis, tenant=ECOLE, token=token)
    assert session.phone_ip
    assert session.staged_mime == "image/jpeg"


# ---------------------------------------------------------------------------
# Ce que la page laisse voir
# ---------------------------------------------------------------------------


async def test_la_page_telephone_ne_revele_pas_l_etat_civil(
    public_client: TestClient, redis: FauxRedis
) -> None:
    """Prénom et initiale, le nom de l'école, la nature du geste. Rien d'autre.

    Ni matricule, ni classe, ni date de naissance, ni nom complet : le code peut
    être scanné par n'importe qui.
    """
    token = await _ouvrir(redis)

    reponse = public_client.get(f"{ROUTE}/{ECOLE}/{token}")

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert corps["label"] == "Kouadio A."
    assert corps["school_name"] == "Collège Rostan"
    assert corps["metier"] == "Photo d'élève"
    assert "Assamoi" not in reponse.text
    for interdit in ("matricule", "birth", "class", "subject_id", "owner"):
        assert interdit not in reponse.text.lower()


async def test_les_reponses_publiques_ne_se_mettent_pas_en_cache(
    public_client: TestClient, redis: FauxRedis, sas: Path
) -> None:
    """L'URL porte un jeton : un proxy d'établissement la servirait au suivant."""
    token = await _ouvrir(redis)

    for reponse in (
        public_client.get(f"{ROUTE}/{ECOLE}/{token}"),
        _envoyer(public_client, token, JPEG),
    ):
        assert reponse.status_code == 200, reponse.text
        assert reponse.headers["cache-control"] == "no-store, private"
        assert reponse.headers["x-robots-tag"] == "noindex, nofollow"


# ---------------------------------------------------------------------------
# Le jeton : un seul dépôt, un seul établissement, dix minutes
# ---------------------------------------------------------------------------


async def test_le_meme_jeton_ne_depose_qu_une_fois(
    public_client: TestClient, redis: FauxRedis, sas: Path
) -> None:
    """Le code est affiché sur un écran : deux téléphones peuvent le scanner.

    Sans ce refus, le second dépôt écraserait le premier sans que l'opérateur
    ait rien vu passer.
    """
    token = await _ouvrir(redis)
    assert _envoyer(public_client, token, JPEG).status_code == 200

    seconde = _envoyer(public_client, token, JPEG)

    assert seconde.status_code == 409
    assert len(list(sas.iterdir())) == 1


async def test_un_jeton_d_une_autre_ecole_n_ouvre_rien(
    public_client: TestClient, redis: FauxRedis
) -> None:
    """Une base MySQL par école, mais UNE seule instance Redis.

    Le tenant vient du chemin et entre dans la clé : le jeton d'une école ne
    résout rien dans l'autre.
    """
    token = await _ouvrir(redis, tenant=AUTRE_ECOLE)

    assert public_client.get(f"{ROUTE}/{ECOLE}/{token}").status_code == 404
    assert _envoyer(public_client, token, JPEG).status_code == 404


def test_un_jeton_inconnu_ou_expire_donne_404(public_client: TestClient) -> None:
    """La réponse attendue au bout de dix minutes, pas une panne.

    Expirée et inconnue rendent la même chose : les distinguer dirait à qui
    essaie des jetons lesquels ont existé.
    """
    assert public_client.get(f"{ROUTE}/{ECOLE}/jamais-emis").status_code == 404


# ---------------------------------------------------------------------------
# Ce qui entre dans le sas
# ---------------------------------------------------------------------------


async def test_un_fichier_qui_ment_sur_son_type_est_refuse(
    public_client: TestClient, redis: FauxRedis, sas: Path
) -> None:
    """Le bon `Content-Type`, les mauvais octets : rien n'entre.

    Le type déclaré est une chaîne que le téléphone choisit. Sans ce contrôle,
    le fichier serait promu sous `/uploads/photos/`, servi par le montage
    statique, avec une extension qui ment sur son contenu.
    """
    token = await _ouvrir(redis)

    reponse = _envoyer(public_client, token, PDF, mime="image/jpeg")

    assert reponse.status_code == 400
    assert not list(sas.iterdir())


async def test_un_type_que_la_cible_n_accepte_pas_est_refuse(
    public_client: TestClient, redis: FauxRedis, sas: Path
) -> None:
    """Une photo n'accepte pas le PDF. Une pièce jointe, si — c'est la CIBLE qui décide."""
    token = await _ouvrir(redis)

    reponse = _envoyer(public_client, token, PDF, mime="application/pdf")

    assert reponse.status_code == 400
    assert not list(sas.iterdir())


async def test_un_envoi_refuse_rend_la_main_sans_nouveau_code(
    public_client: TestClient, redis: FauxRedis, sas: Path
) -> None:
    """La donnée mobile coupe, ou le fichier est refusé : « Réessayer » doit suffire.

    La session redevient ouverte, l'échéance ne bouge pas, aucune reprise n'est
    consommée — personne n'a à se relever pour rescanner.
    """
    token = await _ouvrir(redis)
    assert _envoyer(public_client, token, PDF, mime="image/jpeg").status_code == 400

    session = await svc.load_by_token(redis, tenant=ECOLE, token=token)
    assert session.state == "open"
    assert session.retakes_left == svc.MAX_RETAKES

    assert _envoyer(public_client, token, JPEG).status_code == 200


# ---------------------------------------------------------------------------
# Les trois listes codées en dur
# ---------------------------------------------------------------------------


def test_le_prefixe_herite_du_garde_d_envoi_public() -> None:
    """Sans cette entrée : ni plafond de corps, ni quota par minute, ni sémaphore."""
    assert any(g.prefixe == f"{ROUTE}/" for g in _GARDES_ENVOI_PUBLIC)


def test_le_tenant_se_lit_dans_le_chemin() -> None:
    """Sans cette entrée : pas d'erreur, mais la MAUVAISE base ouverte, en silence."""
    assert _tenant_from_public_path(f"{ROUTE}/{ECOLE}/jeton") == ECOLE


def test_les_deux_routes_sont_declarees_ouvertes_avec_leur_raison() -> None:
    """Sans ces entrées : l'intégration continue sort « route sans garde ».

    La liste est de la documentation autant qu'une exception : elle répond à
    « qu'est-ce qui est ouvert sur cette API ». Une raison vide n'y suffit pas.
    """
    import importlib.util
    import sys

    chemin = Path(__file__).resolve().parents[2] / "scripts" / "check_permissions.py"
    spec = importlib.util.spec_from_file_location("check_permissions", chemin)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Le module doit être joignable par son nom avant d'être exécuté : ses
    # `dataclass` résolvent leurs annotations en le cherchant dans `sys.modules`.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    for nom in ("describe_handoff", "deposit_handoff"):
        cle = f"app/routers/public_upload_handoff.py::{nom}"
        assert cle in module.ROUTES_PUBLIQUES
        assert len(module.ROUTES_PUBLIQUES[cle]) > 20
