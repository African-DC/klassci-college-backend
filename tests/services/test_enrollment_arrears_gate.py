"""Le garde : ce qu'une ardoise d'un exercice révolu fait à une réinscription.

Ce que ces tests tiennent, dans l'ordre où ça compte :

- **Les deux portes.** Une inscription naît de deux fonctions du service, et un
  contrôle sur une seule ne sert à rien : la seconde est le formulaire où la
  secrétaire saisit l'élève et son inscription d'un seul geste, et c'est
  précisément par là qu'une réinscription saisie comme un nouvel élève
  passerait.
- **La promotion n'est jamais bloquée.** Trois cents élèves d'un coup, un geste
  de fin d'année. Refuser là produirait autant d'« Erreur inattendue » que de
  refus, puisque `promotion_service` range dans l'imprévu tout ce qui n'est pas
  une validation métier.
- **Le défaut ne fait rien, et ça se mesure.** `off` ne déclenche aucune
  requête sur la moindre dette : on les compte.
- **Le montant du refus suit la permission.** Trois niveaux, et `None` en bas,
  jamais `0` — un zéro se lit « la famille ne doit rien ».

Les tests appellent le service pour de vrai, sur une base réelle : ce qu'ils
gardent est l'existence du garde sur chaque chemin, et cela ne se simule pas.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.database import Base
from app.core.exceptions import BusinessValidationError, EnrollmentBlockedByArrearsError
from app.models.academic import AcademicYear, ArrearsPolicy, Class, Level, SchoolSettings
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus, FeeCategory, FeeVariant
from app.models.user import Student, User
from app.schemas.enrollment import EnrollmentCreate, EnrollmentWithStudentCreate
from app.services import enrollment_service, promotion_service
from app.services.enrollment_arrears import ArrearsClearance
from app.services.finance_visibility import FinanceView

SECRETAIRE = 1
AN_PASSE = 5
AN_COURANT = 1
MATRICULE = "25000042K"
DETTE = Decimal("52000")


# ---------------------------------------------------------------------------
# Décor
# ---------------------------------------------------------------------------


class _AsyncBridge:
    """Une `AsyncSession` de façade posée sur une session synchrone réelle.

    Elle compte ses `execute` : c'est ce compteur qui rend mesurable la
    promesse « pas une requête de plus » du défaut.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self.executions = 0

    async def execute(self, statement: object) -> object:
        self.executions += 1
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()

    async def refresh(self, instance: object, *a: object, **k: object) -> None:
        self._session.refresh(instance)

    def begin_nested(self) -> Any:
        return _TransactionImbriquee(self._session)


class _TransactionImbriquee:
    """`async with db.begin_nested()` sur une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._transaction: Any = None

    async def __aenter__(self) -> Any:
        self._transaction = self._session.begin_nested()
        return self._transaction

    async def __aexit__(self, type_erreur: object, *_: object) -> bool:
        if type_erreur is not None:
            self._transaction.rollback()
            return False
        self._transaction.commit()
        return False


def _politique(session: Session, valeur: ArrearsPolicy, seuil: int = 0) -> None:
    """Règle l'établissement. Aucune ligne au départ : c'est l'état d'un tenant neuf."""
    school = session.execute(select(SchoolSettings)).scalar_one_or_none()
    if school is None:
        school = SchoolSettings(school_name="Collège de Bouaké")
        session.add(school)
    school.arrears_policy = valeur
    school.arrears_block_threshold_xof = seuil
    session.commit()


def _endette(session: Session, montant: Decimal) -> None:
    """Pose une dette sur l'inscription de l'exercice précédent.

    Un frais obligatoire, non exonéré, sans le moindre versement en face : le
    reste dû vaut son montant entier.
    """
    fee = session.execute(select(EnrollmentFee)).scalar_one()
    fee.amount = montant
    session.commit()


@pytest.fixture()
def db() -> Iterator[tuple[_AsyncBridge, Session]]:
    """Un élève inscrit en 2025-2026, qui doit encore, et pas encore réinscrit.

    C'est la situation mesurée en production : la dette d'un exercice révolu,
    invisible des deux portails dès la réinscription, absente de toute vue
    d'ensemble qui exige une année.
    """
    engine = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint_sqlite(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                User(id=SECRETAIRE, email="sophie@ecole.ci", hashed_password="x", role="staff"),
                AcademicYear(
                    id=AN_PASSE,
                    name="2025-2026",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 7, 31),
                    is_current=False,
                ),
                AcademicYear(
                    id=AN_COURANT,
                    name="2026-2027",
                    start_date=date(2026, 9, 1),
                    end_date=date(2027, 7, 31),
                    is_current=True,
                ),
                Level(id=1, name="6ème", order=1),
                Class(id=1, name="6ème A", level_id=1, max_students=40),
                Class(id=2, name="5ème A", level_id=1, max_students=40),
                Student(
                    id=1,
                    first_name="Aminata",
                    last_name="Traoré",
                    enrollment_number=MATRICULE,
                ),
                FeeCategory(id=1, name="Scolarité", is_mandatory=True),
            ]
        )
        session.commit()
        session.add(
            FeeVariant(id=1, fee_category_id=1, academic_year_id=AN_PASSE, amount=Decimal("52000"))
        )
        session.add(
            Enrollment(
                id=1,
                student_id=1,
                class_id=1,
                academic_year_id=AN_PASSE,
                status=EnrollmentStatus.VALIDE,
            )
        )
        session.commit()
        session.add(
            EnrollmentFee(
                id=1,
                enrollment_id=1,
                fee_variant_id=1,
                fee_category_id=1,
                amount=DETTE,
                status=EnrollmentFeeStatus.PENDING,
            )
        )
        session.commit()
        yield _AsyncBridge(session), session

    engine.dispose()


def _guichet(
    *,
    amounts: bool = True,
    status: bool = True,
    may_override: bool = False,
    motif: str | None = None,
) -> ArrearsClearance:
    """L'appelant type : ce que le routeur aurait résolu pour lui."""
    return ArrearsClearance(
        view=FinanceView(amounts=amounts, status=status),
        may_override=may_override,
        override_reason=motif,
    )


async def _reinscrit(bridge: _AsyncBridge, clearance: ArrearsClearance) -> Any:
    """Porte n°1 : `POST /enrollments`, et par elle `/re-enroll`."""
    return await enrollment_service.create_enrollment(
        bridge,  # type: ignore[arg-type]
        EnrollmentCreate(student_id=1, class_id=2, academic_year_id=AN_COURANT),
        created_by=SECRETAIRE,
        arrears=clearance,
    )


async def _saisit_comme_nouveau(bridge: _AsyncBridge, clearance: ArrearsClearance) -> Any:
    """Porte n°2 : `POST /enrollments/with-student`, le formulaire du guichet."""
    return await enrollment_service.create_enrollment_with_student(
        bridge,  # type: ignore[arg-type]
        EnrollmentWithStudentCreate(
            first_name="Aminata",
            last_name="Traoré",
            class_id=2,
            academic_year_id=AN_COURANT,
            enrollment_number=MATRICULE,
        ),
        created_by=SECRETAIRE,
        arrears=clearance,
    )


# ---------------------------------------------------------------------------
# Les deux portes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_reinscription_est_refusee(db: tuple[_AsyncBridge, Session]) -> None:
    """Porte n°1 : le chemin de la réinscription, celui qui fait sortir la dette."""
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    with pytest.raises(EnrollmentBlockedByArrearsError) as refus:
        await _reinscrit(bridge, _guichet())

    assert refus.value.status_code == 402, (
        "« il faut payer » n'est pas « vous n'avez pas le droit »"
    )
    assert refus.value.payload["code"] == "ENROLLMENT_BLOCKED_BY_ARREARS"
    assert session.execute(select(Enrollment)).scalars().all() == [session.get(Enrollment, 1)], (
        "un refus n'écrit rien"
    )


@pytest.mark.asyncio
async def test_le_formulaire_nouvel_eleve_est_garde_aussi(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """Porte n°2, et c'est tout l'enjeu : sans elle, le blocage se contourne d'un clic.

    La secrétaire saisit l'élève et son inscription d'un seul geste. Elle tape
    le matricule que la famille lui donne — c'est le signal de doublon que le
    dépôt tient pour le plus sûr — et la dette est retrouvée avant qu'une
    seule ligne ne soit écrite.
    """
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    with pytest.raises(EnrollmentBlockedByArrearsError):
        await _saisit_comme_nouveau(bridge, _guichet())

    assert session.execute(select(Student)).scalars().all() == [session.get(Student, 1)], (
        "le garde s'exécute avant la création de l'élève : rien ne reste derrière"
    )


@pytest.mark.asyncio
async def test_un_eleve_reellement_nouveau_passe(db: tuple[_AsyncBridge, Session]) -> None:
    """Sans matricule connu, il n'y a rien à rapprocher, et rien à refuser.

    Refuser sur une ressemblance de nom retiendrait un vrai nouvel élève qui
    porte le nom de son cousin, et il n'existe aucun recours au guichet.
    """
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    cree = await enrollment_service.create_enrollment_with_student(
        bridge,  # type: ignore[arg-type]
        EnrollmentWithStudentCreate(
            first_name="Aminata",
            last_name="Traoré",
            class_id=2,
            academic_year_id=AN_COURANT,
            enrollment_number="26000001A",
        ),
        created_by=SECRETAIRE,
        arrears=_guichet(),
    )

    assert cree.student_id != 1


# ---------------------------------------------------------------------------
# La promotion n'est pas un guichet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_promotion_de_masse_nest_jamais_bloquee(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """Un geste de fin d'année passe, quelle que soit la politique de l'école.

    Et il passe SANS ERREUR, ce qui est le point : `execute_promotion` range
    dans « Erreur inattendue, voir les logs » tout ce qui n'est pas une
    `BusinessValidationError`. Un refus poli y deviendrait quarante-trois
    lignes opaques le jour de la promotion.
    """
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    resultat = await promotion_service.execute_promotion(
        bridge,  # type: ignore[arg-type]
        source_ay_id=AN_PASSE,
        target_ay_id=AN_COURANT,
        class_mapping={1: 2},
        executed_by=SECRETAIRE,
    )

    assert resultat.error_count == 0, resultat.errors
    assert resultat.promoted_count == 1


@pytest.mark.asyncio
async def test_la_clause_de_masse_ne_lit_meme_pas_le_reglage(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """`INFORM_ONLY` sort à la première ligne : pas même la lecture du singleton.

    C'est ce qui garde une promotion de trois cents élèves aussi coûteuse
    qu'avant ce lot.
    """
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    from app.services import enrollment_arrears

    avant = bridge.executions
    await enrollment_arrears.ensure_enrollable(
        bridge,  # type: ignore[arg-type]
        student_id=1,
        year=session.get(AcademicYear, AN_COURANT),
        actor_id=SECRETAIRE,
        clearance=ArrearsClearance.INFORM_ONLY,
    )
    assert bridge.executions == avant


# ---------------------------------------------------------------------------
# Le défaut, et le seuil
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_off_ne_declenche_aucune_requete_sur_la_dette(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """Une école qui n'a rien réglé ne paie pas une requête de plus.

    Une seule lecture, celle du singleton des réglages, et le garde rend la
    main : `policy_in_force` ne lui donne ni politique ni seuil, donc rien à
    demander sur la moindre dette. C'est la forme du retour qui le garantit,
    et on la mesure ici plutôt que de la commenter.
    """
    bridge, session = db
    _politique(session, ArrearsPolicy.OFF)

    from app.services import enrollment_arrears

    avant = bridge.executions
    await enrollment_arrears.ensure_enrollable(
        bridge,  # type: ignore[arg-type]
        student_id=1,
        year=session.get(AcademicYear, AN_COURANT),
        actor_id=SECRETAIRE,
        clearance=_guichet(),
    )
    assert bridge.executions - avant == 1


@pytest.mark.asyncio
async def test_informer_ne_refuse_pas(db: tuple[_AsyncBridge, Session]) -> None:
    """`inform` affiche la dette au guichet et inscrit quand même."""
    bridge, session = db
    _politique(session, ArrearsPolicy.INFORM)

    cree = await _reinscrit(bridge, _guichet())

    assert cree.academic_year_id == AN_COURANT


@pytest.mark.asyncio
async def test_le_seuil_laisse_passer_en_dessous(db: tuple[_AsyncBridge, Session]) -> None:
    """Sous le seuil, et jusqu'à lui, on inscrit. C'est le sens littéral du réglage.

    Une école qui fixe 50 000 F dit « au-delà de 50 000 » : une famille qui
    doit exactement 50 000 n'est pas au-delà.
    """
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK, seuil=50_000)
    _endette(session, Decimal("50000"))

    cree = await _reinscrit(bridge, _guichet())

    assert cree.academic_year_id == AN_COURANT


@pytest.mark.asyncio
async def test_le_seuil_refuse_au_dela(db: tuple[_AsyncBridge, Session]) -> None:
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK, seuil=50_000)
    _endette(session, Decimal("50001"))

    with pytest.raises(EnrollmentBlockedByArrearsError):
        await _reinscrit(bridge, _guichet())


@pytest.mark.asyncio
async def test_une_annee_soldee_ne_bloque_rien(db: tuple[_AsyncBridge, Session]) -> None:
    """Un frais exonéré n'est plus dû : la famille ne traîne aucune ardoise."""
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)
    fee = session.get(EnrollmentFee, 1)
    fee.status = EnrollmentFeeStatus.WAIVED
    session.commit()

    cree = await _reinscrit(bridge, _guichet())

    assert cree.academic_year_id == AN_COURANT


# ---------------------------------------------------------------------------
# Les trois niveaux de visibilité du montant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qui_lit_les_paiements_voit_le_montant(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """`payments:read` : le chiffre, et la phrase qui le nomme."""
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    with pytest.raises(EnrollmentBlockedByArrearsError) as refus:
        await _reinscrit(bridge, _guichet(amounts=True, status=True))

    detail = refus.value.payload
    assert detail["arrears_amount"] == 52000.0
    assert detail["has_arrears"] is True
    assert "52 000 FCFA" in detail["message"]
    assert "2025-2026" in detail["message"]


@pytest.mark.asyncio
async def test_qui_ne_lit_que_letat_a_un_booleen_et_pas_un_franc(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """`payments:status:read` : on valide un dossier sans lire la situation du foyer.

    Le montant est `None`, **jamais `0`** : un zéro se lit « la famille ne doit
    rien », ce qui est un mensonge. Et il ne fuit pas non plus par la phrase.
    """
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    with pytest.raises(EnrollmentBlockedByArrearsError) as refus:
        await _reinscrit(bridge, _guichet(amounts=False, status=True))

    detail = refus.value.payload
    assert detail["arrears_amount"] is None
    assert detail["has_arrears"] is True
    assert "52" not in detail["message"], "le chiffre ne doit pas revenir par la phrase"


@pytest.mark.asyncio
async def test_qui_ne_lit_rien_ne_lit_rien(db: tuple[_AsyncBridge, Session]) -> None:
    """Ni montant ni état : `None` des deux côtés.

    Le motif du refus, lui, reste dit — sans lui, la personne au guichet ne
    saurait pas vers qui envoyer la famille. Ce qui se tait, c'est le chiffre,
    pas la raison.
    """
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    with pytest.raises(EnrollmentBlockedByArrearsError) as refus:
        await _reinscrit(bridge, _guichet(amounts=False, status=False))

    detail = refus.value.payload
    assert detail["arrears_amount"] is None
    assert detail["has_arrears"] is None
    assert "régulariser" in detail["message"]


@pytest.mark.asyncio
async def test_le_refus_dit_que_la_derogation_existe_sans_dire_qui_lexerce(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """`can_override` est un booléen : l'écran propose, il ne nomme personne."""
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    with pytest.raises(EnrollmentBlockedByArrearsError) as sans_droit:
        await _reinscrit(bridge, _guichet(may_override=False))
    with pytest.raises(EnrollmentBlockedByArrearsError) as avec_droit:
        await _reinscrit(bridge, _guichet(may_override=True))

    assert sans_droit.value.payload["can_override"] is False
    assert avec_droit.value.payload["can_override"] is True, (
        "avoir le droit ne suffit pas : il faut aussi un motif"
    )


# ---------------------------------------------------------------------------
# La dérogation, et sa trace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deroger_exige_un_motif(db: tuple[_AsyncBridge, Session]) -> None:
    """Sans motif, le journal dirait qu'on est passé outre sans dire pourquoi."""
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    with pytest.raises(EnrollmentBlockedByArrearsError):
        await _reinscrit(bridge, _guichet(may_override=True, motif="   "))


@pytest.mark.asyncio
async def test_la_derogation_passe_et_se_journalise(db: tuple[_AsyncBridge, Session]) -> None:
    """C'est le seul geste qu'aucun croisement de journaux ne reconstitue.

    La ligne d'inscription existera, mais rien dedans ne dirait qu'on est passé
    outre une dette, ni pourquoi.
    """
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)

    cree = await _reinscrit(
        bridge, _guichet(may_override=True, motif="Bourse DRENA promise, dossier en cours")
    )

    assert cree.academic_year_id == AN_COURANT
    traces = [
        t
        for t in session.execute(select(AuditLog)).scalars().all()
        if t.entity_type == "enrollment_arrears_override"
    ]
    assert len(traces) == 1
    trace = traces[0]
    assert trace.user_id == SECRETAIRE
    assert trace.notes == "Bourse DRENA promise, dossier en cours"
    assert trace.new_values["arrears_amount"] == 52000.0
    assert trace.new_values["academic_year_id"] == AN_COURANT


@pytest.mark.asyncio
async def test_une_derogation_sur_une_inscription_qui_echoue_ne_laisse_rien(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """Le garde ne commet pas : il confie sa ligne au commit de l'appelant.

    C'est la raison pour laquelle il ne peut pas appeler son jumeau
    `document_release_service`, qui fait un `db.commit()` au milieu de sa
    logique : posé dans un `begin_nested()`, il validerait la moitié d'une
    création d'inscription. Ici l'inscription échoue, et il ne reste ni
    dossier ni dérogation.
    """
    bridge, session = db
    _politique(session, ArrearsPolicy.BLOCK)
    session.get(Class, 2).max_students = 0
    session.commit()

    with pytest.raises(BusinessValidationError):
        await _reinscrit(bridge, _guichet(may_override=True, motif="Cas social"))

    session.rollback()
    traces = [
        t
        for t in session.execute(select(AuditLog)).scalars().all()
        if t.entity_type == "enrollment_arrears_override"
    ]
    assert traces == []


# ---------------------------------------------------------------------------
# Le refus est reconnaissable, partout où ça compte
# ---------------------------------------------------------------------------


def test_le_refus_ne_se_confond_avec_aucun_autre() -> None:
    """Ni `HTTPException`, ni `BusinessValidationError`, et c'est délibéré.

    Sous `BusinessValidationError`, le refus pour dette se confondrait avec
    « la classe est pleine » : deux causes, deux gestes différents au guichet.
    Et `promotion_service` la traite à part, si bien qu'un refus rangé là
    ressortirait comme une erreur de saisie.
    """
    from fastapi import HTTPException

    erreur = EnrollmentBlockedByArrearsError({"message": "Réinscription bloquée"})

    assert not isinstance(erreur, HTTPException)
    assert not isinstance(erreur, BusinessValidationError)
    assert erreur.status_code == 402
    assert erreur.code == "ENROLLMENT_BLOCKED_BY_ARREARS"


def test_le_detail_structure_arrive_entier_au_client() -> None:
    """Le handler dédié passe devant celui d'`AppException`, qui aplatirait tout.

    Sans lui, l'écran recevrait la phrase et rien d'autre : ni le montant, ni
    `can_override`, donc aucun moyen de proposer la dérogation.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.exceptions import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/essai")
    async def _essai() -> None:
        raise EnrollmentBlockedByArrearsError(
            {
                "code": "ENROLLMENT_BLOCKED_BY_ARREARS",
                "message": "Réinscription bloquée",
                "arrears_amount": None,
                "has_arrears": True,
                "student_id": 1,
                "academic_year_id": 1,
                "can_override": True,
            }
        )

    reponse = TestClient(app, raise_server_exceptions=False).get("/essai")

    assert reponse.status_code == 402
    detail = reponse.json()["detail"]
    assert detail["arrears_amount"] is None
    assert detail["has_arrears"] is True
    assert detail["can_override"] is True


def test_le_motif_de_derogation_ne_voyage_pas_dans_l_url() -> None:
    """Un motif nomme une famille : il n'a rien à faire dans une adresse.

    « Cas social », « la mère est décédée » — une URL finit dans les journaux
    d'accès du serveur et chez tous les intermédiaires, en clair et pour
    toujours. Le dépôt porte déjà cette règle pour le motif de purge
    (`tests/test_enrollment_purge.py`) ; elle vaut ici pour la même raison.

    Il a d'abord voyagé dans l'adresse, par imitation d'un jumeau qui le fait
    encore. Ce test empêche le retour, et il vise les TROIS créations : une
    seule route qui l'y remettrait suffirait à ressortir le motif en clair.
    """
    from app.main import app

    chemins = {"/enrollments", "/enrollments/with-student", "/enrollments/re-enroll"}
    postes = {
        getattr(r, "path", None): r
        for r in app.routes
        if getattr(r, "path", None) in chemins and "POST" in getattr(r, "methods", set())
    }

    # Sur un poste sans les bibliotheques natives, `app.main` ne monte qu'une
    # partie des routeurs. Un test qui echouerait la deviendrait un rouge
    # permanent de plus, et un rouge permanent finit par ne plus se lire.
    if set(postes) != chemins:
        pytest.skip("les routes d'inscription ne sont pas montees dans cet environnement")

    for chemin, route in postes.items():
        noms = {p.name for p in route.dependant.query_params}
        assert "override_reason" not in noms, f"{chemin} le remet dans l'adresse"
