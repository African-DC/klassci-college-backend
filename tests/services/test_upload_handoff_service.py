"""Le jeton de reprise, et le registre des cibles.

Ce que ces tests gardent
========================

Trois proprietes, et elles ne sont pas de meme nature.

1. **La cle Redis porte l'etablissement.** Il y a une base MySQL par ecole mais
   UNE seule instance Redis. Une cle sans segment de tenant ferait du jeton
   d'une ecole une porte ouverte dans une autre. C'est la faute la plus grave
   possible ici, et elle serait invisible en recette mono-etablissement.

2. **Un jeton n'ouvre qu'un seul depot.** Le code 2D est affiche sur un ecran,
   dans une salle : deux telephones peuvent le scanner. Un seul doit pouvoir
   deposer, sinon le second ecrase le premier sans que l'operateur voie rien.

3. **Le registre dit tout de sa cible.** Les plafonds, les types acceptes, le
   prefixe de nom de fichier et le droit exige viennent de la ligne du registre,
   pas d'une regle globale. Une piece jointe accepte le PDF et dix megaoctets,
   une photo ni l'un ni l'autre.

Le faux Redis, et ce qu'il ne prouve pas
========================================

Le depot n'a ni `fakeredis` ni serveur Redis en integration continue. Le faux
ci-dessous n'EXECUTE PAS le Lua : il en rejoue la semantique en Python. Ce que
ces tests verrouillent est donc le CONTRAT — un seul gagnant, un decompte qui ne
passe pas sous zero, une echeance qui ne bouge pas — et l'enchainement des
appels, pas la syntaxe des scripts. Celle-ci se verifie sur un vrai Redis, et
c'est ecrit ici pour que personne ne croie le contraire.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.dependencies import TokenData
from app.core.uploads import DOCUMENTS, LOGOS, PHOTOS, SIGNATURES
from app.services import upload_handoff_service as service
from app.services.upload_handoff_service import (
    MAX_RETAKES,
    SESSION_TTL_SECONDS,
    TARGETS,
    claim_for_upload,
    close_session,
    discreet_label,
    ensure_owner,
    get_target,
    load_by_token,
    load_session,
    mark_proposed,
    open_session,
    public_view,
    release_claim,
    request_retake,
)
from app.utils import handoff_storage

ECOLE = "rostan"
AUTRE_ECOLE = "wourri"
OPERATEUR = 7
JPEG = b"\xff\xd8\xff" + b"0" * 64


# ---------------------------------------------------------------------------
# Le faux Redis
# ---------------------------------------------------------------------------


class _Pipeline:
    """Redis-py met les commandes en file de facon synchrone, puis `execute`."""

    def __init__(self, redis: "FauxRedis") -> None:
        self._redis = redis
        self._file: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def hset(self, key: str, *, mapping: dict[str, str]) -> "_Pipeline":
        self._file.append(("hset", (key,), {"mapping": mapping}))
        return self

    def expire(self, key: str, ttl: int) -> "_Pipeline":
        self._file.append(("expire", (key, ttl), {}))
        return self

    def set(self, key: str, value: str, *, ex: int | None = None) -> "_Pipeline":
        self._file.append(("set", (key, value), {"ex": ex}))
        return self

    async def execute(self) -> list[Any]:
        return [
            await getattr(self._redis, nom)(*args, **kwargs) for nom, args, kwargs in self._file
        ]


class FauxRedis:
    """Le sous-ensemble de Redis que le service utilise, et rien de plus.

    `eval` ne lit pas le Lua : il reconnait le script et rejoue son effet. Voir
    l'avertissement en tete de module.
    """

    def __init__(self) -> None:
        self.donnees: dict[str, Any] = {}
        self.ttl: dict[str, int] = {}
        self.expirations: list[tuple[str, int]] = []

    def pipeline(self) -> _Pipeline:
        return _Pipeline(self)

    async def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        self.donnees.setdefault(key, {}).update(mapping)
        return len(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        valeur = self.donnees.get(key)
        return dict(valeur) if isinstance(valeur, dict) else {}

    async def get(self, key: str) -> str | None:
        valeur = self.donnees.get(key)
        return valeur if isinstance(valeur, str) else None

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        self.donnees[key] = value
        if ex is not None:
            self.ttl[key] = ex
            self.expirations.append((key, ex))
        return True

    async def expire(self, key: str, ttl: int) -> bool:
        self.ttl[key] = ttl
        self.expirations.append((key, ttl))
        return True

    async def delete(self, *keys: str) -> int:
        efface = 0
        for key in keys:
            efface += 1 if self.donnees.pop(key, None) is not None else 0
            self.ttl.pop(key, None)
        return efface

    async def eval(self, script: str, numkeys: int, *args: Any) -> int:
        cles = [str(a) for a in args[:numkeys]]
        argv = [str(a) for a in args[numkeys:]]
        hachage = self.donnees.get(cles[0])
        if not isinstance(hachage, dict):
            hachage = {}

        if script == service._TRANSITION_SCRIPT:
            if hachage.get("state") != argv[0]:
                return 0
            hachage["state"] = argv[1]
            return 1

        if script == service._DEPOT_SCRIPT:
            if hachage.get("state") != argv[0]:
                return 0
            hachage.update(
                state=argv[1],
                staged_file=argv[2],
                staged_mime=argv[3],
                staged_client_name=argv[4],
                phone_ip=argv[5],
            )
            return 1

        if script == service._REPRISE_SCRIPT:
            if hachage.get("state") != argv[0]:
                return -1
            restant = int(hachage.get("retakes_left", "0"))
            if restant <= 0:
                return -2
            hachage.update(state=argv[1], retakes_left=str(restant - 1))
            return restant - 1

        raise AssertionError(f"script Lua inconnu du faux Redis : {script!r}")


@pytest.fixture
def redis() -> FauxRedis:
    return FauxRedis()


@pytest.fixture
def sas(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    racine = tmp_path / "handoff"
    racine.mkdir()
    monkeypatch.setattr(handoff_storage, "HANDOFF_ROOT", racine)
    return racine


async def _session_ouverte(redis: FauxRedis, *, tenant: str = ECOLE, **kwargs: Any):
    defauts: dict[str, Any] = {
        "target_kind": "student_photo",
        "owner_user_id": OPERATEUR,
        "label": "Kouadio A.",
        "subject_id": 42,
    }
    defauts.update(kwargs)
    return await open_session(redis, tenant=tenant, **defauts)


# ---------------------------------------------------------------------------
# Le registre
# ---------------------------------------------------------------------------


def test_les_sept_cibles_du_premier_jour_sont_la() -> None:
    """Le registre est la liste close de ce qui peut etre depose par telephone."""
    assert set(TARGETS) == {
        "student_photo",
        "teacher_photo",
        "staff_photo",
        "profile_photo",
        "school_logo",
        "school_signature",
        "student_document",
    }


def test_une_cible_inconnue_est_refusee() -> None:
    with pytest.raises(HTTPException) as erreur:
        get_target("payment_receipt")
    assert erreur.value.status_code == 400


@pytest.mark.parametrize(
    ("cible", "prefixe"),
    [
        ("student_photo", "42"),
        ("teacher_photo", "teacher_42"),
        ("staff_photo", "staff_42"),
        ("profile_photo", "u42"),
        ("school_logo", "logo"),
        ("school_signature", "signature"),
        ("student_document", "s42"),
    ],
)
def test_le_prefixe_est_celui_de_la_route_existante(cible: str, prefixe: str) -> None:
    """Les fichiers deja en base suivent ces conventions.

    Un depot par telephone ne doit pas fabriquer une troisieme facon de nommer
    la photo d'un eleve : ce qui est ecrit ici est ce qu'ecrit deja
    `POST /admin/students/{id}/photo`.
    """
    assert TARGETS[cible].prefix_for(42) == prefixe


@pytest.mark.parametrize(
    ("cible", "sorte"),
    [
        ("student_photo", PHOTOS),
        ("teacher_photo", PHOTOS),
        ("staff_photo", PHOTOS),
        ("profile_photo", PHOTOS),
        ("school_logo", LOGOS),
        ("school_signature", SIGNATURES),
        ("student_document", DOCUMENTS),
    ],
)
def test_chaque_cible_vise_la_sorte_qui_la_sert(cible: str, sorte: object) -> None:
    assert TARGETS[cible].upload_kind is sorte


def test_seule_la_piece_jointe_accepte_le_pdf() -> None:
    """La garde MIME est celle de la cible, pas une table unique pour tous.

    C'est ce qui rend la cible `student_document` realisable : avec la table des
    photos, elle aurait leve un 400 sur chaque PDF — et le PDF est precisement
    ce qu'on classe dans un dossier d'eleve.
    """
    assert TARGETS["student_document"].extension_pour("application/pdf") == "pdf"
    for cible in TARGETS.values():
        if cible.kind != "student_document":
            with pytest.raises(HTTPException) as erreur:
                cible.extension_pour("application/pdf")
            assert erreur.value.status_code == 400


def test_le_plafond_de_la_piece_jointe_est_celui_des_documents() -> None:
    """Dix megaoctets pour un document, cinq pour une photo. Deja vrai ailleurs."""
    assert TARGETS["student_document"].max_bytes == DOCUMENTS.max_bytes
    assert TARGETS["student_photo"].max_bytes == PHOTOS.max_bytes
    assert TARGETS["student_document"].max_bytes > TARGETS["student_photo"].max_bytes


def test_un_type_refuse_nomme_les_formats_acceptes() -> None:
    with pytest.raises(HTTPException) as erreur:
        TARGETS["student_photo"].extension_pour("image/gif")
    assert "JPG" in erreur.value.detail or "JPEG" in erreur.value.detail


def test_seule_la_piece_jointe_reclame_un_complement() -> None:
    """`add_student_document` exige un type de document ; les photos n'exigent rien."""
    assert TARGETS["student_document"].extras == ("document_type",)
    for cible in TARGETS.values():
        if cible.kind != "student_document":
            assert cible.extras == ()


def test_toute_cible_sait_ecrire_ce_qu_elle_recoit() -> None:
    """Une cible sans finaliseur serait un depot qui n'atterrit nulle part."""
    for cible in TARGETS.values():
        assert cible.finalise is not None


# ---------------------------------------------------------------------------
# Les droits : lus dans la matrice, jamais inventes
# ---------------------------------------------------------------------------


def _slugs_deja_exiges_par_les_routes() -> set[str]:
    routeurs = Path(__file__).resolve().parents[2] / "app" / "routers"
    # Pas de quantificateur imbrique : `(?:"..."\s*,?\s*)+` fait exploser le
    # retour arriere sur une entree taillee pour, et ce motif lit des fichiers
    # du depot. On capture l'interieur de l'appel d'un seul tenant, sans
    # alternance, puis on en extrait les chaines.
    motif = re.compile(r"require_(?:any_)?permission\(([^()]*)\)")
    slugs: set[str] = set()
    for chemin in routeurs.rglob("*.py"):
        for groupe in motif.findall(chemin.read_text(encoding="utf-8")):
            slugs.update(re.findall(r'"([^"]+)"', groupe))
    return slugs


def test_aucune_cible_n_invente_un_droit() -> None:
    """Chaque slug du registre est deja exige par une route du depot.

    Inventer ici un droit que la matrice ne connait pas donnerait un bouton que
    personne ne peut utiliser, et une ecole qui voudrait l'accorder ne le
    trouverait nulle part dans son ecran des roles.
    """
    connus = _slugs_deja_exiges_par_les_routes()
    assert connus, "aucun slug releve : le test ne verifie plus rien"
    for cible in TARGETS.values():
        if cible.permission is not None:
            assert cible.permission in connus, cible.kind


def test_la_seule_cible_sans_droit_est_un_self_service() -> None:
    """`permission=None` ne veut pas dire « ouvert ».

    Il veut dire que le geste est de changer SA propre photo : la route
    existante `/profile/me/photo` n'exige elle non plus aucun slug, et
    `set_my_photo` porte la regle. Le sujet est donc force a l'appelant, ce qui
    interdit d'ouvrir une session sur le profil d'un autre.
    """
    sans_droit = [c for c in TARGETS.values() if c.permission is None]
    assert [c.kind for c in sans_droit] == ["profile_photo"]
    for cible in sans_droit:
        assert cible.subject == "self"


async def test_une_cible_self_service_ne_demande_rien_a_la_matrice() -> None:
    appelant = TokenData(user_id=OPERATEUR, tenant_id=ECOLE, email="a@b.ci")
    assert await service.caller_may_open(None, appelant, TARGETS["profile_photo"]) is True


# ---------------------------------------------------------------------------
# Le sujet, et les complements
# ---------------------------------------------------------------------------


async def test_une_photo_de_profil_vise_toujours_l_appelant(redis: FauxRedis) -> None:
    """Le sujet est force, jamais lu de la requete.

    Sans cela, quiconque peut ouvrir une session sur cette cible remplacerait la
    photo d'un collegue en passant son identifiant.
    """
    session, _ = await _session_ouverte(
        redis, target_kind="profile_photo", subject_id=999, owner_user_id=OPERATEUR
    )
    assert session.subject_id == OPERATEUR


async def test_une_cible_d_etablissement_n_a_pas_de_sujet(redis: FauxRedis) -> None:
    session, _ = await _session_ouverte(redis, target_kind="school_logo", subject_id=42)
    assert session.subject_id is None


async def test_une_cible_qui_exige_un_destinataire_le_reclame(redis: FauxRedis) -> None:
    with pytest.raises(HTTPException) as erreur:
        await _session_ouverte(redis, target_kind="teacher_photo", subject_id=None)
    assert erreur.value.status_code == 400


async def test_la_photo_d_eleve_s_ouvre_sans_fiche(redis: FauxRedis) -> None:
    """A l'inscription, la photo est prise AVANT que l'eleve existe.

    Sans ce mode, la reprise par telephone raterait precisement l'ecran ou elle
    est la plus utile : celui ou l'operateur n'a pas encore d'identifiant.
    """
    session, _ = await _session_ouverte(redis, subject_id=None)
    assert session.subject_id is None
    assert session.mode == "stage-only"


async def test_avec_une_fiche_le_serveur_finalise(redis: FauxRedis) -> None:
    session, _ = await _session_ouverte(redis, subject_id=42)
    assert session.mode == "finalise"


async def test_la_piece_jointe_reclame_son_type_a_l_ouverture(redis: FauxRedis) -> None:
    """Le decouvrir a la confirmation reviendrait a refuser une photo deja prise."""
    with pytest.raises(HTTPException) as erreur:
        await _session_ouverte(redis, target_kind="student_document", subject_id=42)
    assert erreur.value.status_code == 400
    assert "document_type" in erreur.value.detail


async def test_le_type_de_document_voyage_avec_la_session(redis: FauxRedis) -> None:
    session, _ = await _session_ouverte(
        redis,
        target_kind="student_document",
        subject_id=42,
        extras={"document_type": "Extrait de naissance"},
    )
    relue = await load_session(redis, tenant=ECOLE, session_id=session.id)
    assert relue.extras["document_type"] == "Extrait de naissance"


async def test_un_complement_vide_ne_passe_pas(redis: FauxRedis) -> None:
    with pytest.raises(HTTPException):
        await _session_ouverte(
            redis,
            target_kind="student_document",
            subject_id=42,
            extras={"document_type": "   "},
        )


# ---------------------------------------------------------------------------
# L'etablissement dans la cle : le piege mortel
# ---------------------------------------------------------------------------


async def test_les_deux_cles_portent_l_etablissement(redis: FauxRedis) -> None:
    """Une base par ecole, mais UNE instance Redis pour toutes."""
    await _session_ouverte(redis)
    assert redis.donnees
    for cle in redis.donnees:
        assert f":{ECOLE}:" in cle


async def test_le_jeton_d_une_ecole_n_ouvre_rien_dans_une_autre(redis: FauxRedis) -> None:
    """La faute la plus grave possible ici, et invisible en recette mono-ecole."""
    _, jeton = await _session_ouverte(redis, tenant=ECOLE)

    with pytest.raises(HTTPException) as erreur:
        await load_by_token(redis, tenant=AUTRE_ECOLE, token=jeton)

    assert erreur.value.status_code == 404


async def test_l_identifiant_d_une_ecole_n_ouvre_rien_dans_une_autre(redis: FauxRedis) -> None:
    session, _ = await _session_ouverte(redis, tenant=ECOLE)

    with pytest.raises(HTTPException) as erreur:
        await load_session(redis, tenant=AUTRE_ECOLE, session_id=session.id)

    assert erreur.value.status_code == 404


@pytest.mark.parametrize("tenant", ["", "ROSTAN", "ros:tan", "ros*", "../local", "-rostan"])
async def test_un_segment_d_etablissement_douteux_est_refuse(redis: FauxRedis, tenant: str) -> None:
    """Le tenant arrive du chemin d'une URL publique : c'est une entree.

    Un `:` melangerait deux espaces de noms, un `*` ouvrirait un motif de
    recherche. On refuse plutot que d'echapper.
    """
    with pytest.raises(HTTPException) as erreur:
        await _session_ouverte(redis, tenant=tenant)
    assert erreur.value.status_code == 400


# ---------------------------------------------------------------------------
# Le jeton lui-meme
# ---------------------------------------------------------------------------


async def test_le_jeton_n_est_stocke_nulle_part_en_clair(redis: FauxRedis) -> None:
    """Redis est sauvegarde, exporte, et lu par le support.

    Un jeton en clair dans une cle serait un mot de passe dans un journal. Seul
    son SHA-256 sert de cle, comme pour un jeton d'acces personnel.
    """
    _, jeton = await _session_ouverte(redis)

    for cle, valeur in redis.donnees.items():
        assert jeton not in cle
        if isinstance(valeur, str):
            assert jeton not in valeur
        else:
            assert all(jeton not in v for v in valeur.values())


async def test_le_jeton_et_l_identifiant_sont_deux_secrets(redis: FauxRedis) -> None:
    """L'ordinateur ne manipule que l'identifiant, le telephone que le jeton.

    L'un ne se deduit pas de l'autre : sinon l'operateur pourrait fabriquer le
    lien du telephone, et quiconque scanne le code pourrait sonder la session.
    """
    session, jeton = await _session_ouverte(redis)
    assert jeton != session.id
    assert session.id not in jeton
    assert jeton not in session.id


async def test_les_deux_cles_expirent_ensemble(redis: FauxRedis) -> None:
    await _session_ouverte(redis)
    assert len(redis.ttl) == 2
    assert set(redis.ttl.values()) == {SESSION_TTL_SECONDS}


async def test_une_session_inconnue_donne_404(redis: FauxRedis) -> None:
    """Expiree ou jamais ouverte rendent la meme chose : distinguer renseignerait."""
    with pytest.raises(HTTPException) as erreur:
        await load_session(redis, tenant=ECOLE, session_id="inexistante")
    assert erreur.value.status_code == 404


async def test_un_jeton_inconnu_donne_404(redis: FauxRedis) -> None:
    with pytest.raises(HTTPException) as erreur:
        await load_by_token(redis, tenant=ECOLE, token="jamais-emis")
    assert erreur.value.status_code == 404


# ---------------------------------------------------------------------------
# Un jeton, un depot
# ---------------------------------------------------------------------------


async def test_le_premier_telephone_prend_la_main(redis: FauxRedis) -> None:
    _, jeton = await _session_ouverte(redis)

    session = await claim_for_upload(redis, tenant=ECOLE, token=jeton)

    relue = await load_session(redis, tenant=ECOLE, session_id=session.id)
    assert relue.state == "receiving"


async def test_le_second_telephone_est_refuse(redis: FauxRedis) -> None:
    """Le code 2D est affiche dans une salle : deux telephones peuvent le scanner.

    Sans cette prise unique, le second depot ecraserait le premier et l'operateur
    confirmerait une photo qu'il n'a pas vue arriver.
    """
    _, jeton = await _session_ouverte(redis)
    await claim_for_upload(redis, tenant=ECOLE, token=jeton)

    with pytest.raises(HTTPException) as erreur:
        await claim_for_upload(redis, tenant=ECOLE, token=jeton)

    assert erreur.value.status_code == 409


async def test_un_envoi_echoue_rend_la_session_sans_nouveau_code(redis: FauxRedis) -> None:
    """La donnee mobile coupe au milieu : « Réessayer » doit suffire.

    Le fichier est encore dans le telephone, l'echeance n'a pas bouge, personne
    n'a a se relever pour rescanner.
    """
    _, jeton = await _session_ouverte(redis)
    session = await claim_for_upload(redis, tenant=ECOLE, token=jeton)

    await release_claim(redis, session)

    reprise = await claim_for_upload(redis, tenant=ECOLE, token=jeton)
    assert reprise.id == session.id


async def test_le_depot_pose_le_fichier_et_l_etat_ensemble(redis: FauxRedis) -> None:
    """Une session `proposed` sans fichier afficherait un apercu vide."""
    _, jeton = await _session_ouverte(redis)
    session = await claim_for_upload(redis, tenant=ECOLE, token=jeton)

    await mark_proposed(
        redis,
        session,
        staged_file="abc_12345678.jpg",
        staged_mime="image/jpeg",
        client_name="IMG_0042.JPG",
        phone_ip="41.207.0.9",
    )

    relue = await load_session(redis, tenant=ECOLE, session_id=session.id)
    assert relue.state == "proposed"
    assert relue.staged_file == "abc_12345678.jpg"
    assert relue.staged_mime == "image/jpeg"
    assert relue.staged_client_name == "IMG_0042.JPG"
    assert relue.phone_ip == "41.207.0.9"


async def test_on_ne_depose_pas_sans_avoir_pris_la_main(redis: FauxRedis) -> None:
    session, _ = await _session_ouverte(redis)

    with pytest.raises(HTTPException) as erreur:
        await mark_proposed(
            redis,
            session,
            staged_file="abc_12345678.jpg",
            staged_mime="image/jpeg",
            client_name=None,
            phone_ip=None,
        )

    assert erreur.value.status_code == 409


async def test_l_adresse_du_telephone_est_conservee(redis: FauxRedis) -> None:
    """C'est la seule trace de qui a reellement pris la photo."""
    _, jeton = await _session_ouverte(redis)
    session = await claim_for_upload(redis, tenant=ECOLE, token=jeton)
    await mark_proposed(
        redis,
        session,
        staged_file="abc_12345678.jpg",
        staged_mime="image/jpeg",
        client_name=None,
        phone_ip="41.207.0.9",
    )

    relue = await load_session(redis, tenant=ECOLE, session_id=session.id)
    assert relue.phone_ip == "41.207.0.9"


# ---------------------------------------------------------------------------
# Reprendre
# ---------------------------------------------------------------------------


async def _deposer(redis: FauxRedis, sas: Path, jeton: str) -> str:
    session = await claim_for_upload(redis, tenant=ECOLE, token=jeton)
    nom = await handoff_storage.write_staged(
        _envoi(), session_id=session.id.replace("-", ""), extension="jpg", max_bytes=4096
    )
    await mark_proposed(
        redis,
        session,
        staged_file=nom,
        staged_mime="image/jpeg",
        client_name=None,
        phone_ip=None,
    )
    return nom


def _envoi():
    import io

    from fastapi import UploadFile
    from starlette.datastructures import Headers

    return UploadFile(
        file=io.BytesIO(JPEG),
        filename="envoi.bin",
        headers=Headers({"content-type": "image/jpeg"}),
    )


async def test_reprendre_jette_le_fichier_et_rouvre(redis: FauxRedis, sas: Path) -> None:
    session, jeton = await _session_ouverte(redis)
    nom = await _deposer(redis, sas, jeton)
    depot = await load_session(redis, tenant=ECOLE, session_id=session.id)

    restant = await request_retake(redis, depot)

    assert restant == MAX_RETAKES - 1
    assert not (sas / nom).exists()
    relue = await load_session(redis, tenant=ECOLE, session_id=session.id)
    assert relue.state == "open"


async def test_reprendre_ne_repousse_pas_l_echeance(redis: FauxRedis, sas: Path) -> None:
    """Trois reprises ne doivent pas faire vivre une demi-heure un code affiche."""
    session, jeton = await _session_ouverte(redis)
    echeance = session.deadline
    await _deposer(redis, sas, jeton)
    depot = await load_session(redis, tenant=ECOLE, session_id=session.id)

    avant = len(redis.expirations)
    await request_retake(redis, depot)

    relue = await load_session(redis, tenant=ECOLE, session_id=session.id)
    assert relue.deadline == echeance
    assert len(redis.expirations) == avant, "le TTL a ete repousse"


async def test_le_plafond_de_reprises_finit_par_fermer(redis: FauxRedis, sas: Path) -> None:
    session, jeton = await _session_ouverte(redis)

    for reste in range(MAX_RETAKES - 1, -1, -1):
        await _deposer(redis, sas, jeton)
        depot = await load_session(redis, tenant=ECOLE, session_id=session.id)
        assert await request_retake(redis, depot) == reste

    await _deposer(redis, sas, jeton)
    depot = await load_session(redis, tenant=ECOLE, session_id=session.id)
    with pytest.raises(HTTPException) as erreur:
        await request_retake(redis, depot)
    assert erreur.value.status_code == 409
    assert "nouvelle session" in erreur.value.detail


async def test_on_ne_reprend_pas_ce_qui_n_est_pas_arrive(redis: FauxRedis) -> None:
    session, _ = await _session_ouverte(redis)

    with pytest.raises(HTTPException) as erreur:
        await request_retake(redis, session)

    assert erreur.value.status_code == 409


# ---------------------------------------------------------------------------
# Fermer
# ---------------------------------------------------------------------------


async def test_fermer_efface_la_session_et_son_fichier(redis: FauxRedis, sas: Path) -> None:
    """La revocation doit etre reelle, pas cosmetique.

    Le jeton cesse d'ouvrir quoi que ce soit a l'instant meme, sans attendre
    l'echeance, et la photo d'eleve ne reste pas dans le sas.
    """
    session, jeton = await _session_ouverte(redis)
    nom = await _deposer(redis, sas, jeton)
    depot = await load_session(redis, tenant=ECOLE, session_id=session.id)

    await close_session(redis, depot)

    assert not (sas / nom).exists()
    with pytest.raises(HTTPException):
        await load_session(redis, tenant=ECOLE, session_id=session.id)
    with pytest.raises(HTTPException):
        await load_by_token(redis, tenant=ECOLE, token=jeton)


# ---------------------------------------------------------------------------
# La propriete de la session, et ce que le telephone voit
# ---------------------------------------------------------------------------


async def test_une_session_appartient_a_qui_l_a_ouverte(redis: FauxRedis) -> None:
    """Deux personnes du secretariat detiennent le meme droit.

    Sans cette verification, l'une confirmerait la photo que l'autre attend, sur
    l'eleve qui n'est pas devant elle.
    """
    session, _ = await _session_ouverte(redis, owner_user_id=OPERATEUR)

    ensure_owner(session, OPERATEUR)
    with pytest.raises(HTTPException) as erreur:
        ensure_owner(session, OPERATEUR + 1)
    assert erreur.value.status_code == 403


@pytest.mark.parametrize(
    ("prenom", "nom", "attendu"),
    [
        ("Kouadio", "AKISSI", "Kouadio A."),
        ("Aya", "n'guessan", "Aya N."),
        ("Yao", None, "Yao"),
        (None, "KOFFI", "K."),
        (None, None, "Sans nom"),
        ("  Adjoua  ", "  Bamba ", "Adjoua B."),
    ],
)
def test_le_libelle_ne_dit_qu_un_prenom_et_une_initiale(
    prenom: str | None, nom: str | None, attendu: str
) -> None:
    """Un code 2D peut etre scanne par n'importe qui dans un couloir.

    Y afficher le nom complet d'un mineur, son matricule ou sa classe
    transformerait une reprise de photo en divulgation.
    """
    assert discreet_label(prenom, nom) == attendu


async def test_la_page_du_telephone_ne_recoit_aucun_etat_civil(redis: FauxRedis) -> None:
    """De quoi peindre une page et cadrer une photo, rien de plus."""
    session, _ = await _session_ouverte(redis, subject_id=42, label="Kouadio A.")

    vue = public_view(session)

    assert set(vue) == {"label", "kind", "metier", "accepts", "max_bytes", "state", "expires_at"}
    assert "42" not in str(vue["label"])
    assert "subject_id" not in vue
    assert "owner_user_id" not in vue
    assert isinstance(vue["expires_at"], datetime)
