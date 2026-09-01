"""« Cet élève est-il nouveau ? » et le droit de répondre « je ne sais pas ».

La secrétaire coche une case, et cette case décide d'un montant. Le serveur
peut l'aider en lisant l'historique, mais il ne le fait que si l'école a
déclaré cet historique exploitable. Le collège Rostan ne l'a pas fait :
l'application vient d'y être déployée, la base ne porte que l'année en cours,
et l'année 2025-2026 sera reconstituée petit à petit. Répondre « aucune
inscription antérieure, donc nouveau » y facturerait les frais d'entrée à tous
les anciens élèves.

Deux garde-fous, donc, et ces tests couvrent les deux : le réglage déclaré par
l'école, puis, une fois déclaré, la lecture prudente de l'historique. C'est la
règle que le rapport approfondi tenait déjà pour sa colonne Red / Non Red,
avec le même critère et les mêmes statuts.

Les tests tournent sur SQLite, via le module standard : ils exécutent le vrai
SQL du service, jointures comprises, sans base MySQL à provisionner.
"""

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear, Class, SchoolSettings
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.services import enrollment_history

AY_COURANTE = 2026
AY_PRECEDENTE = 2025

LEVEL_6E = 10
LEVEL_5E = 11
CLASSE_6E_A = 1
CLASSE_5E_A = 2

FIDELE = 100  # inscrit l'an dernier
ARRIVANT = 101  # jamais vu ici
AUTRE_FIDELE = 102  # un second ancien, pour que l'historique ne tienne pas à un seul


class _AsyncBridge:
    """L'allure d'une `AsyncSession` sur une session synchrone."""

    def __init__(self, session: Session) -> None:
        self.session = session

    async def execute(self, statement: object) -> object:
        return self.session.execute(statement)  # type: ignore[arg-type]


def _sqlite_schema() -> list[Table]:
    """Le schéma des quatre tables utiles, transposé pour SQLite.

    SQLite ne numérote automatiquement que les colonnes déclarées
    « INTEGER PRIMARY KEY » : les `BIGINT` du modèle refuseraient tout INSERT
    sans identifiant. On travaille sur une copie du schéma, jamais sur les
    tables du modèle, que les autres tests lisent.
    """
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)

    utiles = []
    for nom in ("academic_years", "classes", "enrollments", "school_settings"):
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        utiles.append(table)
    return utiles


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    """Une base neuve par test : deux années, deux classes, aucune inscription.

    L'établissement est celui de Rostan au premier jour : ses réglages
    existent, et il n'a rien déclaré sur son historique. C'est l'état par
    défaut, celui qu'il faut tester en premier parce que c'est celui de toutes
    les écoles qui viennent d'être déployées.
    """
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                SchoolSettings(id=1, school_name="College Rostan"),
                AcademicYear(
                    id=AY_PRECEDENTE,
                    name="2025-2026",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 7, 31),
                ),
                AcademicYear(
                    id=AY_COURANTE,
                    name="2026-2027",
                    start_date=date(2026, 9, 1),
                    end_date=date(2027, 7, 31),
                ),
                Class(id=CLASSE_6E_A, name="6eme A", level_id=LEVEL_6E),
                Class(id=CLASSE_5E_A, name="5eme A", level_id=LEVEL_5E),
            ]
        )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


def _inscrire(
    db: _AsyncBridge,
    enrollment_id: int,
    student_id: int,
    *,
    annee: int = AY_PRECEDENTE,
    classe: int = CLASSE_6E_A,
    statut: EnrollmentStatus = EnrollmentStatus.VALIDE,
) -> None:
    db.session.add(
        Enrollment(
            id=enrollment_id,
            student_id=student_id,
            class_id=classe,
            academic_year_id=annee,
            status=statut,
        )
    )
    db.session.flush()


def _declarer_historique_exploitable(db: _AsyncBridge) -> None:
    """Le geste que l'école fait dans ses réglages, une fois sa reprise finie."""
    reglages = db.session.query(SchoolSettings).one()
    reglages.enrollment_history_is_reliable = True
    db.session.flush()


def _cohorte_rattachee(db: _AsyncBridge, combien: int = 5) -> None:
    """Une année en cours dont les élèves sont bien rattachés au passé.

    Le garde-fou ne mesure plus « existe-t-il une inscription antérieure » mais
    « quelle part de la cohorte en cours y est rattachée ». Sans cette
    cohorte-là, la couverture est nulle et la suggestion répond `None` avant
    même de regarder l'élève : les tests qui portent sur le prédicat par élève
    ont besoin qu'on ait d'abord franchi la mesure.
    """
    for rang in range(combien):
        eleve = 900 + rang
        _inscrire(db, 900 + rang * 2, eleve, annee=AY_PRECEDENTE)
        _inscrire(db, 901 + rang * 2, eleve, annee=AY_COURANTE)


async def _suggestion(db: _AsyncBridge, student_id: int) -> tuple[bool | None, str]:
    return await enrollment_history.suggest_new_student(
        db,  # type: ignore[arg-type]
        student_id,
        AY_COURANTE,
    )


# ---------------------------------------------------------------------------
# Le premier garde-fou : tant que l'école n'a rien déclaré, on ne déduit pas
# ---------------------------------------------------------------------------


async def test_rend_null_quand_l_ecole_n_a_rien_declare(db: _AsyncBridge) -> None:
    """Le cas Rostan au premier jour. Le serveur ne tranche pas, et la phrase
    le dit à la secrétaire au lieu de la laisser deviner."""
    suggested, reason = await _suggestion(db, ARRIVANT)

    assert suggested is None
    assert reason


async def test_le_reglage_a_false_ne_deduit_rien_meme_avec_un_historique_complet(
    db: _AsyncBridge,
) -> None:
    """LE test qui protège Rostan pendant sa reprise.

    L'année précédente est là, deux élèves y figurent, et l'un des deux n'est
    pas notre arrivant : la déduction serait techniquement possible. Elle ne
    doit pas avoir lieu, parce que la reprise est en cours et que la moitié
    des dossiers n'est pas encore ressaisie. Conclure « nouveau » ici
    facturerait le droit d'entrée à des élèves présents depuis six ans, et la
    famille le découvrirait sur sa facture.
    """
    _inscrire(db, 1, FIDELE)
    _inscrire(db, 2, AUTRE_FIDELE)

    suggested, reason = await _suggestion(db, ARRIVANT)

    assert suggested is None
    assert reason
    assert (
        await enrollment_history.deduce_new_student(
            db,  # type: ignore[arg-type]
            ARRIVANT,
            AY_COURANTE,
        )
        is None
    )


async def test_le_reglage_a_false_ne_declare_pas_ancien_non_plus(db: _AsyncBridge) -> None:
    """Ni « nouveau » ni « ancien » : le serveur se tait dans les deux sens.
    Cet élève-là EST inscrit depuis l'an dernier, et le dire quand même
    reviendrait à faire confiance à un historique que l'école n'a pas validé."""
    _inscrire(db, 1, FIDELE)

    suggested, _reason = await _suggestion(db, FIDELE)

    assert suggested is None


async def test_un_etablissement_sans_ligne_de_reglages_ne_deduit_pas(
    db: _AsyncBridge,
) -> None:
    """Un tenant fraîchement provisionné n'a pas encore de réglages. L'absence
    vaut « pas déclaré » : c'est le seul défaut qui ne facture rien."""
    db.session.query(SchoolSettings).delete()
    db.session.flush()
    _inscrire(db, 1, FIDELE)

    suggested, _reason = await _suggestion(db, ARRIVANT)

    assert suggested is None


# ---------------------------------------------------------------------------
# Une école qui a déclaré son historique : la déduction d'avant, inchangée
# ---------------------------------------------------------------------------


async def test_rend_null_meme_quand_l_annee_anterieure_existe_mais_reste_vide(
    db: _AsyncBridge,
) -> None:
    """Le second garde-fou, celui qui vaut même après la déclaration. L'année
    2025-2026 est bien créée, personne n'y a été réinscrit. Une année vide ne
    dit rien de qui était là."""
    _declarer_historique_exploitable(db)
    assert AY_PRECEDENTE in {y.id for y in db.session.query(AcademicYear).all()}

    suggested, _reason = await _suggestion(db, ARRIVANT)

    assert suggested is None


async def test_une_inscription_de_l_annee_courante_ne_fait_pas_un_historique(
    db: _AsyncBridge,
) -> None:
    """Les camarades de classe de cette année ne prouvent rien sur l'an dernier."""
    _declarer_historique_exploitable(db)
    _inscrire(db, 1, FIDELE, annee=AY_COURANTE)

    suggested, _reason = await _suggestion(db, ARRIVANT)

    assert suggested is None


async def test_un_eleve_deja_inscrit_l_an_dernier_n_est_pas_nouveau(db: _AsyncBridge) -> None:
    _declarer_historique_exploitable(db)
    _cohorte_rattachee(db)
    _inscrire(db, 1, FIDELE)

    suggested, reason = await _suggestion(db, FIDELE)

    assert suggested is False
    assert reason


async def test_un_eleve_inconnu_est_nouveau_des_lors_que_l_ecole_a_un_passe(
    db: _AsyncBridge,
) -> None:
    """L'historique est déclaré, d'autres élèves y figurent, et celui-ci n'y
    est pas : la suggestion devient légitime."""
    _declarer_historique_exploitable(db)
    _cohorte_rattachee(db)
    _inscrire(db, 1, FIDELE)

    suggested, _reason = await _suggestion(db, ARRIVANT)

    assert suggested is True


async def test_un_redoublant_reste_un_ancien(db: _AsyncBridge) -> None:
    """Il refait sa 6ème : le niveau ne change rien à son ancienneté."""
    _declarer_historique_exploitable(db)
    _cohorte_rattachee(db)
    _inscrire(db, 1, FIDELE, classe=CLASSE_6E_A)

    suggested, _reason = await _suggestion(db, FIDELE)

    assert suggested is False


# ---------------------------------------------------------------------------
# Le périmètre des statuts, partagé avec le rapport approfondi
# ---------------------------------------------------------------------------


async def test_une_inscription_rejetee_ne_compte_pas_comme_un_passage(
    db: _AsyncBridge,
) -> None:
    """Un dossier refusé n'a jamais occupé de place : le compter ferait passer
    pour ancien un élève qui n'a jamais mis les pieds dans l'école."""
    _declarer_historique_exploitable(db)
    _cohorte_rattachee(db)
    _inscrire(db, 1, FIDELE, statut=EnrollmentStatus.REJETE)
    _inscrire(db, 2, ARRIVANT)

    suggested, _reason = await _suggestion(db, FIDELE)

    assert suggested is True


async def test_une_inscription_en_validation_compte_comme_un_passage(
    db: _AsyncBridge,
) -> None:
    """C'est le périmètre déjà retenu par les statistiques DREN : on ne le
    change pas d'un usage à l'autre."""
    _declarer_historique_exploitable(db)
    _cohorte_rattachee(db)
    _inscrire(db, 1, FIDELE, statut=EnrollmentStatus.EN_VALIDATION)

    suggested, _reason = await _suggestion(db, FIDELE)

    assert suggested is False


def test_les_statuts_comptes_sont_ceux_du_rapport_approfondi() -> None:
    """Deux listes de statuts finiraient par diverger, et une seule bougerait
    le jour où quelqu'un ajoute un statut d'inscription."""
    from app.services.deep_report import _context

    assert _context._COUNTED_STATUSES is enrollment_history.COUNTED_STATUSES


# ---------------------------------------------------------------------------
# Le prédicat groupé, celui du rapport approfondi
# ---------------------------------------------------------------------------


async def test_le_rapport_lit_les_couples_eleve_niveau_deja_frequentes(
    db: _AsyncBridge,
) -> None:
    """La requête groupée du rapport et le prédicat unitaire du formulaire
    répondent à la même question sur les mêmes lignes."""
    _inscrire(db, 1, FIDELE, classe=CLASSE_6E_A)

    couples, has_history = await enrollment_history.levels_attended_before(
        db,  # type: ignore[arg-type]
        date(2026, 9, 1),
    )

    assert has_history is True
    assert (FIDELE, LEVEL_6E) in couples


async def test_le_rapport_n_affirme_rien_sans_historique(db: _AsyncBridge) -> None:
    """`has_history` à False laisse la colonne Red / Non Red vide, plutôt que
    d'annoncer « Non Red » pour tout le monde."""
    couples, has_history = await enrollment_history.levels_attended_before(
        db,  # type: ignore[arg-type]
        date(2026, 9, 1),
    )

    assert has_history is False
    assert couples == set()


# ---------------------------------------------------------------------------
# La déduction faite à la création d'une inscription
# ---------------------------------------------------------------------------


async def test_la_deduction_rend_null_sans_historique(db: _AsyncBridge) -> None:
    """Le serveur ne remplit pas la case à la place de l'école."""
    deduit = await enrollment_history.deduce_new_student(
        db,  # type: ignore[arg-type]
        ARRIVANT,
        AY_COURANTE,
    )

    assert deduit is None


async def test_la_deduction_reprend_des_que_l_ecole_a_declare(db: _AsyncBridge) -> None:
    """Le réglage n'éteint pas la fonctionnalité, il la conditionne : une fois
    la reprise terminée et déclarée, l'aide à la saisie revient telle quelle."""
    _declarer_historique_exploitable(db)
    _cohorte_rattachee(db)
    _inscrire(db, 1, FIDELE)

    assert (
        await enrollment_history.deduce_new_student(
            db,  # type: ignore[arg-type]
            ARRIVANT,
            AY_COURANTE,
        )
        is True
    )
    assert (
        await enrollment_history.deduce_new_student(
            db,  # type: ignore[arg-type]
            FIDELE,
            AY_COURANTE,
        )
        is False
    )


async def test_le_reglage_se_relit_a_chaque_suggestion(db: _AsyncBridge) -> None:
    """L'école lève son réglage au milieu d'une journée de guichet : la
    suggestion suivante doit en tenir compte, sans redémarrage."""
    _cohorte_rattachee(db)
    _inscrire(db, 1, FIDELE)

    avant, _ = await _suggestion(db, ARRIVANT)
    _declarer_historique_exploitable(db)
    apres, _ = await _suggestion(db, ARRIVANT)

    assert avant is None
    assert apres is True


async def test_une_annee_inconnue_est_refusee(db: _AsyncBridge) -> None:
    """Mieux vaut un 404 lisible qu'une suggestion calculée sur une date vide."""
    with pytest.raises(NotFoundError):
        await enrollment_history.suggest_new_student(
            db,  # type: ignore[arg-type]
            ARRIVANT,
            9999,
        )


# ---------------------------------------------------------------------------
# La couverture : deux cohortes disjointes ne font pas un historique
# ---------------------------------------------------------------------------


async def test_deux_cohortes_disjointes_ne_deduisent_rien(db: _AsyncBridge) -> None:
    """LE test de ce garde-fou, et le scénario mesuré sur la prod de Rostan.

    Quarante-cinq inscriptions existent sur l'année antérieure, toutes valides,
    et aucun des élèves de l'année en cours n'y figure. L'ancien garde-fou
    concluait sur l'existence d'UNE ligne : il en trouvait quarante-cinq, il
    passait, et tous les anciens élèves étaient déduits « nouveaux » puis
    facturés du dossier d'entrée.

    Assez d'historique pour que le garde-fou s'efface, pas assez pour qu'il
    dise vrai. C'est exactement cette configuration qui doit rendre `None`.
    """
    _declarer_historique_exploitable(db)
    # L'année passée, une cohorte entière.
    for rang in range(9):
        _inscrire(db, 100 + rang, 100 + rang, annee=AY_PRECEDENTE)
    # Cette année, une cohorte qui ne la recoupe pas du tout.
    for rang in range(9):
        _inscrire(db, 200 + rang, 200 + rang, annee=AY_COURANTE)

    suggested, reason = await _suggestion(db, 200)

    assert suggested is None
    assert "0 des 9" in reason


async def test_la_couverture_compte_les_eleves_pas_les_inscriptions(
    db: _AsyncBridge,
) -> None:
    """La mesure porte sur des élèves distincts, des deux côtés."""
    _inscrire(db, 1, FIDELE, annee=AY_PRECEDENTE)
    _inscrire(db, 2, FIDELE, annee=AY_COURANTE)
    _inscrire(db, 3, ARRIVANT, annee=AY_COURANTE)

    couverture = await enrollment_history.history_coverage(
        db,  # type: ignore[arg-type]
        AY_COURANTE,
    )

    assert couverture.enrolled_this_year == 2
    assert couverture.with_anterior == 1
    assert couverture.ratio == 0.5
    assert couverture.is_sufficient is True


async def test_une_annee_courante_vide_n_est_pas_une_couverture_totale(
    db: _AsyncBridge,
) -> None:
    """Zéro sur zéro ne vaut pas cent pour cent : il n'y a rien à rapprocher."""
    _inscrire(db, 1, FIDELE, annee=AY_PRECEDENTE)

    couverture = await enrollment_history.history_coverage(
        db,  # type: ignore[arg-type]
        AY_COURANTE,
    )

    assert couverture.enrolled_this_year == 0
    assert couverture.is_sufficient is False


async def test_la_couverture_ignore_les_dossiers_refuses(db: _AsyncBridge) -> None:
    """Les statuts comptés viennent de `anterior_enrollments`, pas d'un second
    filtre écrit ici : un dossier rejeté ne rattache personne."""
    _inscrire(db, 1, FIDELE, annee=AY_PRECEDENTE, statut=EnrollmentStatus.REJETE)
    _inscrire(db, 2, FIDELE, annee=AY_COURANTE)

    couverture = await enrollment_history.history_coverage(
        db,  # type: ignore[arg-type]
        AY_COURANTE,
    )

    assert couverture.enrolled_this_year == 1
    assert couverture.with_anterior == 0
    assert couverture.is_sufficient is False


def test_le_seuil_est_bas_a_dessein() -> None:
    """Il ne juge pas la proportion d'arrivants, qui est une variable légitime :
    il détecte deux jeux de données qui ne se recouvrent pas."""
    assert 0 < enrollment_history.COUVERTURE_MINIMALE <= 0.5
