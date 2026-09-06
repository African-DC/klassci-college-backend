"""Les routes du cote ordinateur : ouvrir, sonder, regarder, confirmer, reprendre.

Ce que ces tests gardent
========================

1. **Le droit de la CIBLE, redemande a chaque geste.** Le slug vit dans le
   registre, donc il ne se resout qu'a l'execution : aucune dependance FastAPI
   ne peut le figer. Le risque propre a ce montage est qu'on verifie a
   l'ouverture et plus jamais ensuite — un droit retire pendant les dix minutes
   d'une session laisserait alors confirmer.

2. **Une session appartient a l'operateur qui l'a ouverte.** Deux personnes du
   secretariat detiennent le meme droit et travaillent en parallele ; sans cette
   regle, l'une confirme la photo que l'autre attend, sur l'eleve qui n'est pas
   devant elle.

3. **Rien n'est ecrit avant que quelqu'un ait regarde.** C'est la propriete qui
   rend acceptable qu'un jeton porteur circule dans un code photographiable. Un
   depot sans destinataire ne doit RIEN promouvoir, et deux clics sur
   « Confirmer » ne doivent produire qu'une seule ecriture.

4. **L'apercu ne se met pas en cache.** Il diffuse la photo d'un mineur que
   personne n'a encore validee.

Le faux Redis est celui des tests du service : le meme contrat, rejoue en
Python. Il ne prouve pas la syntaxe des scripts Lua — cela se verifie sur un
vrai Redis, et c'est ecrit la-bas aussi.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user
from app.main import app
from app.services import upload_handoff_service as svc
from app.utils import handoff_storage
from tests.services.test_upload_handoff_service import FauxRedis

SERVICE = "app.services.upload_handoff_service"
#: On remplace un nom LA OU IL EST UTILISE, pas la ou il est re-expose.
#: `resolve_permission` vit dans la mecanique de session ; le remplacer sur
#: la porte d'entree ne changerait rien a ce que la session appelle.
SESSION_MODULE = "app.services.upload_handoff._session"
JPEG = b"\xff\xd8\xff" + b"0" * 64
COLLEGUE = TokenData(user_id=99, tenant_id="local", email="autre@college.ci")


@pytest.fixture
def redis_partage(client: TestClient) -> FauxRedis:
    """Un faux Redis servi a l'application pour toute la duree du test."""
    from app.core.redis import get_redis

    faux = FauxRedis()
    app.dependency_overrides[get_redis] = lambda: faux
    return faux


@pytest.fixture
def sas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    racine = tmp_path / "handoff"
    racine.mkdir()
    monkeypatch.setattr(handoff_storage, "HANDOFF_ROOT", racine)
    return racine


@pytest.fixture
def autorise() -> Any:
    """La matrice des droits repond oui. A retourner a `False` pour tester le refus."""
    with patch(f"{SESSION_MODULE}.resolve_permission", new_callable=AsyncMock) as resolveur:
        resolveur.return_value = True
        yield resolveur


@pytest.fixture
def eleve_nomme() -> Any:
    """Un eleve en base, avec son nom complet.

    On remplace le depot et non le libelle : ce qui doit etre verifie ici, c'est
    justement que « Assamoi » ne sorte pas de la route. Un faux qui rendrait
    deja « Kouadio A. » ne prouverait rien.
    """
    with patch(
        "app.repositories.admin_repository.get_student_by_id", new_callable=AsyncMock
    ) as charger:
        charger.return_value = SimpleNamespace(id=42, first_name="Kouadio", last_name="Assamoi")
        yield charger


#: L'adresse que le navigateur de l'operateur annonce. Les tests la posent
#: comme le portail la pose : c'est elle, et non une variable de serveur, qui
#: dit ou le telephone doit arriver.
ORIGINE = "https://college.klassci.com"


def _ouvrir(client: TestClient, **corps: Any) -> dict[str, Any]:
    charge = {"target_kind": "student_photo", "subject_id": 42, "origin": ORIGINE}
    charge.update(corps)
    reponse = client.post("/admin/upload-handoff", json=charge)
    assert reponse.status_code == 201, reponse.text
    return reponse.json()


async def _deposer(redis: FauxRedis, sas: Path, ouverte: dict[str, Any]) -> None:
    """Rejoue le geste du telephone : prendre la main par le JETON, puis deposer.

    Le jeton est relu de l'URL du code QR, et pas fabrique ici : c'est ce qui
    verifie au passage que le lien encode dans le code ouvre reellement la
    session — un code QR valide vers un jeton mort se lit comme une panne
    reseau, et se cherche des heures.
    """
    token = ouverte["url"].rsplit("/", 1)[-1]
    session = await svc.claim_for_upload(redis, tenant="local", token=token)
    nom = f"{session.id}_abcd1234.jpg"
    (sas / nom).write_bytes(JPEG)
    await svc.mark_proposed(
        redis,
        session,
        staged_file=nom,
        staged_mime="image/jpeg",
        client_name="IMG_0042.jpg",
        phone_ip="41.66.0.9",
    )


# ---------------------------------------------------------------------------
# Ouvrir
# ---------------------------------------------------------------------------


def test_ouvrir_rend_un_code_qr_et_jamais_le_jeton(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any
) -> None:
    """L'ecran recoit de quoi afficher un code ; le jeton ne vit que dans le lien.

    Deux secrets, deux usages : l'ordinateur pilote sa session par
    l'identifiant, le telephone depose par le jeton. Exposer le second a cote du
    premier rendrait la separation cosmetique.
    """
    corps = _ouvrir(client)

    assert corps["qr_svg"].startswith("<svg")
    assert corps["url"].startswith("https://college.klassci.com/televerser/local/")
    assert corps["state"] == "open"
    assert corps["mode"] == "finalise"
    assert corps["label"] == "Kouadio A."
    assert corps["warnings"] == []
    assert "token" not in corps
    assert corps["id"] not in corps["url"]
    # Le meme libelle s'affichera sur un telephone que n'importe qui peut avoir
    # en main : le nom complet d'un mineur n'a rien a y faire.
    assert "Assamoi" not in str(corps)


def test_sans_le_droit_de_la_cible_aucune_session_n_existe(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any
) -> None:
    """Refuser APRES avoir ouvert laisserait un jeton valide dix minutes."""
    autorise.return_value = False

    reponse = client.post(
        "/admin/upload-handoff", json={"target_kind": "student_photo", "subject_id": 42}
    )

    assert reponse.status_code == 403
    assert redis_partage.donnees == {}


def test_le_droit_demande_est_celui_de_la_cible(
    client: TestClient, redis_partage: FauxRedis, autorise: Any
) -> None:
    """Le slug vient du registre, pas de la signature de la route.

    Le logo de l'etablissement releve d'un droit qui n'a rien a voir avec celui
    d'une photo d'eleve : c'est tout l'interet d'un registre, et c'est ce qui
    interdit de figer un slug a la declaration.
    """
    _ouvrir(client, target_kind="school_logo", subject_id=None)

    assert autorise.await_args.args[2] == "admin:academic-years:update"


def test_une_cible_inconnue_est_refusee(
    client: TestClient, redis_partage: FauxRedis, autorise: Any
) -> None:
    """Le registre est la liste close de ce qui peut etre depose par telephone."""
    reponse = client.post("/admin/upload-handoff", json={"target_kind": "bulletin_de_paie"})
    assert reponse.status_code == 400


# ---------------------------------------------------------------------------
# Sonder, et le droit qui change en cours de route
# ---------------------------------------------------------------------------


def test_le_sondage_rend_l_etat_sans_etat_civil(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any
) -> None:
    """Le meme libelle que le telephone : c'est ce qui permet de les comparer."""
    ouverte = _ouvrir(client)

    corps = client.get(f"/admin/upload-handoff/{ouverte['id']}").json()

    assert corps["state"] == "open"
    assert corps["label"] == "Kouadio A."
    assert corps["staged_mime"] is None


def test_un_droit_retire_pendant_la_session_ferme_la_porte(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any
) -> None:
    """Verifier a l'ouverture seulement laisserait confirmer dix minutes de trop."""
    ouverte = _ouvrir(client)
    autorise.return_value = False

    assert client.get(f"/admin/upload-handoff/{ouverte['id']}").status_code == 403


def test_la_session_d_un_collegue_n_est_pas_la_mienne(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any
) -> None:
    """Deux secretaires ont le meme droit : la permission ne suffit pas a departager."""
    ouverte = _ouvrir(client)
    app.dependency_overrides[get_current_user] = lambda: COLLEGUE

    assert client.get(f"/admin/upload-handoff/{ouverte['id']}").status_code == 403


def test_une_session_expiree_se_lit_comme_une_session_inconnue(
    client: TestClient, redis_partage: FauxRedis, autorise: Any
) -> None:
    """Distinguer les deux dirait a qui essaie des identifiants lesquels ont existe."""
    assert client.get("/admin/upload-handoff/jamais-existe").status_code == 404


# ---------------------------------------------------------------------------
# Regarder
# ---------------------------------------------------------------------------


async def test_l_apercu_diffuse_les_octets_sans_les_mettre_en_cache(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any, sas: Path
) -> None:
    """Une photo non validee ne doit rester ni sur le poste ni dans un proxy."""
    ouverte = _ouvrir(client)
    await _deposer(redis_partage, sas, ouverte)

    reponse = client.get(f"/admin/upload-handoff/{ouverte['id']}/preview")

    assert reponse.status_code == 200
    assert reponse.content == JPEG
    assert reponse.headers["cache-control"] == "no-store, private"
    assert reponse.headers["x-robots-tag"] == "noindex, nofollow"
    assert reponse.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------------------
# Confirmer
# ---------------------------------------------------------------------------


async def test_confirmer_ecrit_la_photo_une_seule_fois(
    client: TestClient,
    redis_partage: FauxRedis,
    autorise: Any,
    eleve_nomme: Any,
    sas: Path,
    tmp_path: Path,
) -> None:
    """Deux clics rapides sur « Confirmer » ne font pas deux ecritures.

    Sur une photo le doublon coute un fichier mort ; sur une piece jointe il
    coute une ligne en base. L'etat passe donc a `done` avant la promotion, et
    de facon indivisible.
    """
    ouverte = _ouvrir(client)
    await _deposer(redis_partage, sas, ouverte)

    with (
        patch("app.core.uploads.UPLOAD_ROOT", tmp_path),
        patch(
            "app.services.admin_service.update_student_photo", new_callable=AsyncMock
        ) as ecrire_la_photo,
    ):
        premiere = client.post(f"/admin/upload-handoff/{ouverte['id']}/confirm")
        seconde = client.post(f"/admin/upload-handoff/{ouverte['id']}/confirm")

    assert premiere.status_code == 200
    assert premiere.json()["url"].startswith("/uploads/photos/42_")
    assert seconde.status_code in {404, 409}
    assert ecrire_la_photo.await_count == 1
    assert list((tmp_path / "photos").iterdir()) != []
    assert list(sas.iterdir()) == [], "le fichier quitte le sas quand il est promu"


async def test_un_depot_sans_destinataire_ne_promeut_rien(
    client: TestClient,
    redis_partage: FauxRedis,
    autorise: Any,
    sas: Path,
    tmp_path: Path,
) -> None:
    """A l'inscription la fiche n'existe pas encore : rien a ecrire, donc rien a sortir.

    Sortir le fichier du sas ici l'attacherait a personne — il resterait servi
    sous `/uploads` sans qu'aucune ligne ne le reference.
    """
    ouverte = _ouvrir(client, subject_id=None)
    assert ouverte["mode"] == "stage-only"
    await _deposer(redis_partage, sas, ouverte)

    with patch("app.core.uploads.UPLOAD_ROOT", tmp_path):
        reponse = client.post(f"/admin/upload-handoff/{ouverte['id']}/confirm")

    assert reponse.status_code == 409
    assert not (tmp_path / "photos").exists()
    assert len(list(sas.iterdir())) == 1, "l'image reste consultable par l'apercu"


# ---------------------------------------------------------------------------
# Reprendre et revoquer
# ---------------------------------------------------------------------------


async def test_reprendre_jette_le_depot_et_rouvre_la_session(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any, sas: Path
) -> None:
    """Le meme code QR reste valable : personne n'a a se relever pour rescanner."""
    ouverte = _ouvrir(client)
    await _deposer(redis_partage, sas, ouverte)

    reponse = client.post(f"/admin/upload-handoff/{ouverte['id']}/retake")

    assert reponse.status_code == 200
    assert reponse.json() == {"state": "open", "retakes_left": svc.MAX_RETAKES - 1}
    assert list(sas.iterdir()) == []
    assert client.get(f"/admin/upload-handoff/{ouverte['id']}").json()["state"] == "open"


async def test_reprendre_ne_repousse_pas_l_echeance(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any, sas: Path
) -> None:
    """Trois reprises ne doivent pas faire vivre une demi-heure un code affiche."""
    ouverte = _ouvrir(client)
    await _deposer(redis_partage, sas, ouverte)

    client.post(f"/admin/upload-handoff/{ouverte['id']}/retake")

    apres = client.get(f"/admin/upload-handoff/{ouverte['id']}").json()
    assert apres["expires_at"] == ouverte["expires_at"]


async def test_revoquer_efface_le_depot_et_la_session(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any, sas: Path
) -> None:
    """La fermeture de l'ecran doit fermer la porte, pas attendre l'echeance."""
    ouverte = _ouvrir(client)
    await _deposer(redis_partage, sas, ouverte)

    # L'appel AVANT l'assertion : `python -O` efface les `assert`, et avec eux
    # la fermeture que le reste du test suppose faite.
    fermeture = client.delete(f"/admin/upload-handoff/{ouverte['id']}")
    assert fermeture.status_code == 204
    assert list(sas.iterdir()) == []
    assert client.get(f"/admin/upload-handoff/{ouverte['id']}").status_code == 404


# ---------------------------------------------------------------------------
# L'adresse publique encodee dans le code
# ---------------------------------------------------------------------------


def test_une_adresse_publique_locale_est_annoncee_a_l_operateur(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any
) -> None:
    """Un code QR vers le reseau local est valide et ne mene nulle part.

    C'est le seul defaut de toute la chaine qui ne produise aucune erreur : le
    telephone dit « site inaccessible », et l'operateur n'a aucun moyen de
    comprendre pourquoi. On le dit sur SON ecran, a l'ouverture.

    L'operateur est ici sur le portail par l'adresse du reseau de l'ecole —
    ce qui arrive des qu'on ouvre l'application depuis un poste du bureau.
    """
    corps = _ouvrir(client, origin="http://192.168.1.40:3000")

    assert len(corps["warnings"]) == 2
    assert "donnée mobile" in corps["warnings"][0]
    assert "HTTP" in corps["warnings"][1]
    # L'avertissement parle de l'adresse que le code porte REELLEMENT.
    assert corps["url"].startswith("http://192.168.1.40:3000/televerser/")


def test_une_origine_hors_allowlist_ne_devient_pas_l_adresse_du_code(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any
) -> None:
    """C'est le navigateur qui annonce l'origine : on ne le croit pas sur parole.

    Sans ce controle, un en-tete forge suffirait a faire pointer le code QR
    d'une ecole vers un site tiers — et l'operateur y verrait un code parfait.
    """
    with patch(f"{SERVICE}.settings") as reglages:
        reglages.PUBLIC_BASE_URL = "https://college.klassci.com"
        corps = _ouvrir(client, origin="https://sitemalveillant.example")

    assert "sitemalveillant" not in corps["url"]
    assert corps["url"].startswith("https://college.klassci.com/televerser/")


def test_sans_adresse_publique_la_session_ne_s_ouvre_pas(
    client: TestClient, redis_partage: FauxRedis, autorise: Any, eleve_nomme: Any
) -> None:
    """Mieux vaut refuser que fabriquer un lien qui designe une autre ecole.

    La variable portait un domaine d'etablissement en valeur par defaut : toute
    installation qui l'oubliait envoyait donc ses telephones chez le voisin,
    avec un jeton qui n'y existe pas. Elle n'en porte plus, et l'absence se dit.
    """
    with patch(f"{SERVICE}.settings") as reglages:
        reglages.PUBLIC_BASE_URL = ""
        reponse = client.post(
            "/admin/upload-handoff",
            json={"target_kind": "student_photo", "subject_id": 42},
        )

    assert reponse.status_code == 503
    assert "PUBLIC_BASE_URL" in reponse.json()["detail"]
