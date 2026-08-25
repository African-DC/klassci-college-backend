"""Supprimer une fiche coupe l'accès ; l'archiver ne le coupe pas.

Le défaut constaté en production : une école renvoie sa comptable,
l'administrateur supprime sa fiche, et la comptable se reconnecte le
lendemain avec son mot de passe. Six comptes ont ainsi survécu à la
suppression de leur fiche sur le locataire de production, tous capables de
s'authentifier.

Ces tests appellent les fonctions réelles — `revoke_access`, `purge_record`,
`auth_service.login`, `_authenticate_jwt` — contre une base factice qui tient
une table `users` en mémoire. Ils ne relisent pas le code source pour y
chercher une ligne : ce qui est vérifié, c'est qu'une authentification échoue,
pas qu'un fichier contient un mot.
"""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.database import current_tenant_id
from app.core.exceptions import UnauthorizedError
from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRoleEnum
from app.services import account_access, archive_service, auth_service
from app.services.account_access import revoke_access

MOT_DE_PASSE = "Caisse@2026"


# ---------------------------------------------------------------------------
# Une base factice qui tient vraiment l'état des comptes
# ---------------------------------------------------------------------------


class _Resultat:
    def __init__(self, valeur: object = None, rowcount: int = 0) -> None:
        self._valeur = valeur
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> object:
        return self._valeur


@dataclass
class _Jeton:
    """Un jeton d'accès personnel, réduit à ce que la révocation en fait."""

    id: int
    user_id: int
    revoked_at: object = None


class _BaseComptes:
    """Session factice : une table `users`, une table de jetons, rien de plus.

    `execute` lit l'ordre SQL rendu par SQLAlchemy plutôt que de simuler un
    moteur : c'est assez pour que `revoke_access` et les fonctions
    d'authentification opèrent sur le MÊME objet `User`, ce qui est tout
    l'intérêt — l'un le désactive, l'autre le relit.
    """

    def __init__(self, comptes: list[User], jetons: list[_Jeton] | None = None) -> None:
        self.comptes = comptes
        self.jetons = jetons or []
        self.ordres: list[str] = []
        self.commits = 0
        #: Rejoue le RESTRICT des clés étrangères qui pointent vers `users`.
        self.compte_a_tenu_une_caisse = False

    async def execute(self, statement: object, *_a: object, **_k: object) -> _Resultat:
        rendu = str(statement).lower()
        self.ordres.append(rendu)
        params = {}
        try:
            params = dict(statement.compile().params)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - ordres sans paramètres
            params = {}
        valeurs = set(params.values())

        if rendu.startswith("delete") and " users" in rendu:
            if self.compte_a_tenu_une_caisse:
                raise IntegrityError(
                    "DELETE FROM users",
                    None,
                    Exception("FOREIGN KEY (`cashier_user_id`) ... ON DELETE RESTRICT"),
                )
            return _Resultat(rowcount=1)

        if rendu.startswith("update") and "personal_access_tokens" in rendu:
            vises = [j for j in self.jetons if j.user_id in valeurs and j.revoked_at is None]
            for jeton in vises:
                jeton.revoked_at = "2026-08-21"
            return _Resultat(rowcount=len(vises))

        if rendu.startswith("select") and "from users" in rendu:
            for compte in self.comptes:
                if compte.id in valeurs or compte.email in valeurs:
                    return _Resultat(compte)
            return _Resultat(None)

        return _Resultat(None)

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


def _compte(user_id: int = 5, email: str = "sophie.yao@college.ci") -> User:
    """Le compte de Mme Yao, secrétaire, tel qu'il existe en base."""
    return User(
        id=user_id,
        email=email,
        hashed_password=hash_password(MOT_DE_PASSE),
        role=UserRoleEnum.STAFF,
        is_active=True,
        must_change_password=False,
    )


@dataclass
class _FichePersonnel:
    """Une fiche personnel déjà placée dans la corbeille."""

    id: int = 12
    user_id: int | None = 5
    first_name: str = "Sophie"
    last_name: str = "Yao"
    archived_at: object = "2026-08-20"
    archived_by: object = 1
    archive_reason: object = "depart de l'etablissement"


def _kind_personnel(fiche: _FichePersonnel) -> archive_service.ArchivableKind:
    """Le type « personnel », branché sur une fiche donnée sans base réelle."""

    async def _charge(_db: object, _ident: int) -> _FichePersonnel:
        return fiche

    async def _supprime(_db: object, _record: object) -> None:
        return None

    return archive_service.ArchivableKind(
        "staff",
        "Le membre du personnel",
        _FichePersonnel,
        _supprime,
        archive_service.owns_user_account,
        load=_charge,
    )


@pytest.fixture
def sans_bruit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Coupe le journal d'audit et le courriel : ils ont leurs propres tests."""

    async def _rien(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr(archive_service, "audit_log", _rien)
    monkeypatch.setattr(archive_service, "notify", _rien)


# ---------------------------------------------------------------------------
# La révocation elle-même
# ---------------------------------------------------------------------------


async def test_revoquer_desactive_le_compte_et_ses_jetons() -> None:
    compte = _compte()
    jetons = [_Jeton(1, compte.id), _Jeton(2, compte.id), _Jeton(3, 99)]
    db = _BaseComptes([compte], jetons)

    revocation = await revoke_access(db, compte.id)

    assert compte.is_active is False
    assert revocation.happened is True
    assert revocation.email == compte.email
    assert revocation.tokens_revoked == 2
    assert [j.revoked_at for j in jetons] == ["2026-08-21", "2026-08-21", None]


async def test_revoquer_ne_supprime_jamais_la_ligne_du_compte() -> None:
    """L'attribution des actes passés tient à l'existence de cette ligne."""
    compte = _compte()
    db = _BaseComptes([compte])

    await revoke_access(db, compte.id)

    assert not any(ordre.startswith("delete") for ordre in db.ordres), db.ordres


async def test_une_fiche_sans_compte_ne_declenche_rien() -> None:
    """Un élève inscrit sans identifiants, une inscription : rien à couper."""
    db = _BaseComptes([])

    revocation = await revoke_access(db, None)

    assert revocation is account_access.NO_ACCOUNT
    assert db.ordres == []


async def test_un_compte_introuvable_est_signale_sans_faire_echouer(caplog) -> None:
    db = _BaseComptes([])

    with caplog.at_level("WARNING"):
        revocation = await revoke_access(db, 4242)

    assert revocation.happened is False
    assert any("4242" in record.getMessage() for record in caplog.records)


async def test_un_compte_deja_desactive_est_annonce_comme_tel() -> None:
    """Ne pas laisser croire à une révocation qui n'a rien changé."""
    compte = _compte()
    compte.is_active = False
    db = _BaseComptes([compte])

    revocation = await revoke_access(db, compte.id)

    assert revocation.was_already_inactive is True
    assert "déjà désactivé" in revocation.sentence()


# ---------------------------------------------------------------------------
# Le geste complet : supprimer la fiche ferme la porte
# ---------------------------------------------------------------------------


async def test_apres_suppression_le_mot_de_passe_ne_connecte_plus(sans_bruit) -> None:
    """Le cas de la comptable renvoyée qui se reconnectait le lendemain."""
    compte = _compte()
    db = _BaseComptes([compte])
    redis = SimpleNamespace()

    jeton = current_tenant_id.set("local")
    try:
        # Avant : elle se connecte.
        reponse, _refresh = await auth_service.login(
            db, _RedisFactice(), compte.email, MOT_DE_PASSE
        )
        assert reponse.user.email == compte.email

        await archive_service.purge_record(
            db,
            _kind_personnel(_FichePersonnel()),
            12,
            reason="Depart de l'etablissement le 20 aout",
            actor_id=1,
        )

        # Après : le même mot de passe est refusé.
        with pytest.raises(UnauthorizedError):
            await auth_service.login(db, redis, compte.email, MOT_DE_PASSE)
    finally:
        current_tenant_id.reset(jeton)


async def test_apres_suppression_un_jeton_deja_emis_est_refuse(sans_bruit) -> None:
    """Un jeton d'accès vit trente minutes : il ne doit pas survivre au geste.

    C'est possible parce que `_authenticate_jwt` relit `users.is_active` en
    base à chaque requête. Si ce n'était plus le cas, ce test tomberait.
    """
    from app.core.dependencies import _authenticate_jwt

    compte = _compte()
    db = _BaseComptes([compte])

    jeton_ctx = current_tenant_id.set("local")
    try:
        acces = create_access_token(user_id=compte.id, tenant_id="local", email=compte.email)

        # Le jeton fonctionne tant que la fiche est là.
        identite = await _authenticate_jwt(acces, db)
        assert identite.user_id == compte.id

        await archive_service.purge_record(
            db,
            _kind_personnel(_FichePersonnel()),
            12,
            reason="Depart de l'etablissement le 20 aout",
            actor_id=1,
        )

        with pytest.raises(UnauthorizedError):
            await _authenticate_jwt(acces, db)
    finally:
        current_tenant_id.reset(jeton_ctx)


async def test_un_compte_qui_a_tenu_une_caisse_se_supprime_quand_meme(sans_bruit) -> None:
    """Huit clés étrangères en RESTRICT pointent vers `users`.

    Supprimer la ligne du compte échouerait donc précisément pour les
    personnes qui ont le plus agi — une caissière, une éducatrice qui a émis
    des convocations. La fiche doit partir malgré tout, et l'accès être coupé.
    """
    compte = _compte()
    db = _BaseComptes([compte])
    db.compte_a_tenu_une_caisse = True

    await archive_service.purge_record(
        db,
        _kind_personnel(_FichePersonnel()),
        12,
        reason="Depart de l'etablissement le 20 aout",
        actor_id=1,
    )

    assert compte.is_active is False
    assert db.commits == 1


async def test_la_revocation_est_lue_avant_que_la_fiche_ne_parte(sans_bruit) -> None:
    """Une fois la fiche détruite, plus rien ne dit quel compte elle ouvrait."""
    compte = _compte()
    db = _BaseComptes([compte])
    fiche = _FichePersonnel()

    async def _supprime(_db: object, record: _FichePersonnel) -> None:
        # La destruction réelle détache la fiche de son compte.
        record.user_id = None

    kind = _kind_personnel(fiche)
    kind = archive_service.ArchivableKind(
        kind.entity_type,
        kind.article,
        kind.model,
        _supprime,
        kind.account_of,
        load=kind.load,
    )

    await archive_service.purge_record(
        db, kind, 12, reason="Depart de l'etablissement le 20 aout", actor_id=1
    )

    assert compte.is_active is False


# ---------------------------------------------------------------------------
# Archiver ne met personne dehors
# ---------------------------------------------------------------------------


async def test_apres_archivage_le_compte_fonctionne_toujours(sans_bruit) -> None:
    """Une secrétaire archivée par erreur ne doit pas se retrouver dehors."""
    compte = _compte()
    db = _BaseComptes([compte])
    fiche = _FichePersonnel(archived_at=None, archived_by=None, archive_reason=None)

    jeton = current_tenant_id.set("local")
    try:
        await archive_service.archive_record(
            db,
            _kind_personnel(fiche),
            12,
            reason="Fiche saisie deux fois a la rentree",
            actor_id=1,
        )

        assert fiche.archived_at is not None
        assert compte.is_active is True
        reponse, _refresh = await auth_service.login(
            db, _RedisFactice(), compte.email, MOT_DE_PASSE
        )
        assert reponse.user.email == compte.email
    finally:
        current_tenant_id.reset(jeton)


async def test_un_archivage_ne_touche_jamais_la_table_des_comptes(sans_bruit) -> None:
    compte = _compte()
    db = _BaseComptes([compte])
    fiche = _FichePersonnel(archived_at=None, archived_by=None, archive_reason=None)

    await archive_service.archive_record(
        db, _kind_personnel(fiche), 12, reason="Fiche saisie deux fois a la rentree", actor_id=1
    )

    for ordre in db.ordres:
        assert not ordre.startswith("update users"), ordre
        assert "personal_access_tokens" not in ordre, ordre


# ---------------------------------------------------------------------------
# Le registre : aucune sorte de fiche ne peut oublier la question
# ---------------------------------------------------------------------------


def test_chaque_sorte_de_fiche_dit_si_elle_ouvre_un_acces() -> None:
    """Une fiche qui porte `user_id` sans le déclarer laisserait un compte
    vivant derrière elle. C'est exactement le défaut corrigé ici."""
    from app.services.admin_service import PARENT_KIND, STAFF_KIND, STUDENT_KIND, TEACHER_KIND
    from app.services.enrollment_archive import ENROLLMENT_KIND

    for kind in (STUDENT_KIND, TEACHER_KIND, STAFF_KIND, PARENT_KIND, ENROLLMENT_KIND):
        porte_un_compte = "user_id" in kind.model.__table__.columns
        declare_un_compte = kind.account_of is archive_service.owns_user_account
        assert declare_un_compte == porte_un_compte, (
            f"{kind.entity_type} : la colonne user_id et la declaration divergent"
        )


def test_l_inscription_n_ouvre_aucun_acces_par_elle_meme() -> None:
    """On se connecte en tant qu'élève, jamais en tant qu'inscription.

    Son `created_by` désigne la secrétaire qui l'a saisie : le couper
    mettrait dehors la mauvaise personne.
    """
    from app.models.enrollment import Enrollment
    from app.services.enrollment_archive import ENROLLMENT_KIND

    assert ENROLLMENT_KIND.account_of is archive_service.carries_no_account
    assert "user_id" not in Enrollment.__table__.columns
    assert "created_by" in Enrollment.__table__.columns


# ---------------------------------------------------------------------------
# Ce que le journal et le courriel en disent
# ---------------------------------------------------------------------------


def test_le_journal_distingue_les_deux_situations() -> None:
    revoque = account_access.AccessRevocation(
        user_id=5, email="sophie.yao@college.ci", tokens_revoked=1
    )
    assert revoque.as_audit_values() == {
        "acces_revoque": True,
        "compte": "sophie.yao@college.ci",
        "compte_id": 5,
        "deja_desactive": False,
        "jetons_revoques": 1,
    }
    assert account_access.NO_ACCOUNT.as_audit_values() == {"acces_revoque": False, "compte": None}


def test_le_courriel_dit_que_l_acces_est_revoque() -> None:
    """« Fiche supprimée » et « fiche supprimée, accès révoqué » ne sont pas
    la même information au lendemain d'un licenciement."""
    from datetime import datetime

    from app.services import deletion_notice_service as notice

    school = SimpleNamespace(
        school_name="Collège Saint-Augustin",
        email=None,
        deletion_notice_emails=None,
        head_master_name="Mme Diallo",
        mailpulse_enabled=False,
        mailpulse_sender_email=None,
        mailpulse_sender_name=None,
    )
    outcome = archive_service.ArchiveOutcome(
        "staff",
        12,
        "Le membre du personnel Yao Sophie",
        "Depart de l'etablissement",
        permanent=True,
        access=account_access.AccessRevocation(
            user_id=5, email="sophie.yao@college.ci", tokens_revoked=2
        ),
    )

    _objet, texte, html = notice.compose_notice(
        outcome, school=school, actor_name="Mme Diallo", occurred_at=datetime(2026, 8, 21, 9, 0)
    )

    for corps in (texte, html):
        assert "Accès révoqué" in corps
        assert "sophie.yao@college.ci" in corps
        assert "2 jetons d'accès personnel" in corps


def test_le_courriel_d_archivage_rassure_sur_l_acces() -> None:
    """Archiver est réversible : le message doit le dire aussi de l'accès."""
    from datetime import datetime

    from app.services import deletion_notice_service as notice

    school = SimpleNamespace(
        school_name="Collège Saint-Augustin",
        email=None,
        deletion_notice_emails=None,
        head_master_name="Mme Diallo",
        mailpulse_enabled=False,
        mailpulse_sender_email=None,
        mailpulse_sender_name=None,
    )
    outcome = archive_service.ArchiveOutcome(
        "staff", 12, "Le membre du personnel Yao Sophie", "Doublon de saisie", permanent=False
    )

    _objet, texte, _html = notice.compose_notice(
        outcome, school=school, actor_name="Mme Diallo", occurred_at=datetime(2026, 8, 21, 9, 0)
    )

    assert "n'est pas touché" in texte
    assert "révoqué" not in texte


class _RedisFactice:
    """Le strict nécessaire pour que `login` stocke son jeton de rafraîchissement."""

    def __init__(self) -> None:
        self.cles: dict[str, str] = {}

    async def setex(self, cle: str, _ttl: int, valeur: str) -> None:
        self.cles[cle] = valeur

    async def exists(self, cle: str) -> int:
        return 1 if cle in self.cles else 0

    async def delete(self, cle: str) -> None:
        self.cles.pop(cle, None)
