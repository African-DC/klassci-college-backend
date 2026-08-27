"""La détection appelée pour de vrai, sur une base réelle.

Le cas qui a motivé tout ceci : 45 élèves de 2025-2026 doivent des arriérés.
S'ils reviennent et que le secrétariat recrée une fiche faute de retrouver le
matricule, l'ardoise reste attachée à l'ancienne et personne ne la réclame.

Ces tests montent un vrai schéma SQLite et interrogent la vraie fonction.
"""

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import Student
from app.services.duplicates.detection import _motifs, chercher_doublons


class _Pont:
    """Une `AsyncSession` de façade sur une session synchrone réelle."""

    def __init__(self, session: Session) -> None:
        self._s = session

    async def execute(self, statement: object) -> object:
        return self._s.execute(statement)  # type: ignore[arg-type]


@pytest.fixture()
def db() -> Iterator[Session]:
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    with Session(moteur) as s:
        s.add_all(
            [
                AcademicYear(
                    id=1,
                    name="2025-2026",
                    start_date=date(2025, 9, 8),
                    end_date=date(2026, 6, 30),
                    is_current=False,
                ),
                AcademicYear(
                    id=2,
                    name="2026-2027",
                    start_date=date(2026, 9, 14),
                    end_date=date(2027, 7, 30),
                    is_current=True,
                ),
                Level(id=1, name="3eme", order=4),
                Class(id=1, name="3eme 2", level_id=1),
                # Trois élèves du fichier réel des arriérés.
                Student(
                    id=1,
                    last_name="KOUASSI",
                    first_name="Aya marie adelaide",
                    enrollment_number="ECER0882",
                ),
                Student(
                    id=2, last_name="KOUASSI", first_name="David", enrollment_number="ECER0864"
                ),
                Student(
                    id=3,
                    last_name="COULIBALY",
                    first_name="Souleymane ben junior",
                    enrollment_number="ECER0734",
                ),
                # L'apostrophe rendait cet élève introuvable par le préfiltre.
                Student(
                    id=4,
                    last_name="N'DRI",
                    first_name="Etiakoun grace naomie",
                    enrollment_number="ECER0516",
                ),
                Student(
                    id=5,
                    last_name="TRAORE",
                    first_name="Cheick moussa",
                    enrollment_number="ECER0344",
                ),
                # Stocke avec l'apostrophe COURBE : celle que produisent les
                # claviers de telephone et les copier-coller depuis Word. Le
                # premier correctif ne traitait que la droite, donc cette fiche
                # restait invisible cote base.
                Student(
                    id=6,
                    last_name="N’GUESSAN",
                    first_name="Ama beatrice",
                    enrollment_number="ECER0901",
                ),
            ]
        )
        s.add(
            Enrollment(
                id=1,
                student_id=1,
                class_id=1,
                academic_year_id=2,
                status=EnrollmentStatus.PROSPECT.value,
            )
        )
        s.commit()
        yield s


@pytest.mark.asyncio
async def test_le_matricule_identique_passe_avant_la_ressemblance(db: Session) -> None:
    """Rien ne « bloque » : le service le dit lui-meme.

    Le nom precedent promettait un blocage que le module ne fait pas, et
    l'assertion doublait la ligne au-dessus. Ce qui compte vraiment est
    l'ordre : une certitude doit arriver avant une ressemblance, sinon
    l'ecran met en avant la moins sure des deux.
    """
    trouves, _ = await chercher_doublons(
        _Pont(db), last_name="KOUASSI", first_name="Aya", enrollment_number="ECER0882"
    )
    assert trouves[0].motif == "matricule"
    assert all(t.motif == "ressemblance" for t in trouves[1:])


@pytest.mark.asyncio
async def test_sans_matricule_la_ressemblance_retrouve_la_fiche(db: Session) -> None:
    # La famille revient sans son papier : c'est le cas qui fabrique les
    # doublons, et celui que le score doit rattraper.
    trouves, _ = await chercher_doublons(
        _Pont(db), last_name="Coulibaly", first_name="souleymane ben junior"
    )
    assert [t.student_id for t in trouves] == [3]
    assert trouves[0].motif == "ressemblance"
    assert trouves[0].ressemblance.juge_sur_peu is True


@pytest.mark.asyncio
async def test_deux_kouassi_distincts_ne_sont_pas_confondus(db: Session) -> None:
    trouves, _ = await chercher_doublons(_Pont(db), last_name="KOUASSI", first_name="David")
    assert [t.student_id for t in trouves] == [2], "l'autre KOUASSI a été signalé à tort"


@pytest.mark.asyncio
async def test_une_inscription_non_validee_est_signalee(db: Session) -> None:
    # Le cœur de la demande : un dossier en attente ne se voit pas dans les
    # listes, et c'est celui-là qu'on recrée.
    trouves, _ = await chercher_doublons(
        _Pont(db),
        last_name="KOUASSI",
        first_name="Aya marie adelaide",
        enrollment_number="ECER0882",
        academic_year_id=2,
    )
    inscription = trouves[0].inscription_annee_courante
    assert inscription is not None
    # Le champ est un objet typé, plus un dictionnaire fourre-tout : une clé
    # mal orthographiée est désormais une erreur, pas un `None` silencieux.
    assert inscription.status == EnrollmentStatus.PROSPECT.value
    assert inscription.class_name == "3eme 2"


@pytest.mark.asyncio
async def test_sans_annee_on_ne_pretend_pas_connaitre_l_inscription(db: Session) -> None:
    trouves, _ = await chercher_doublons(
        _Pont(db),
        last_name="KOUASSI",
        first_name="Aya marie adelaide",
        enrollment_number="ECER0882",
    )
    assert trouves[0].inscription_annee_courante is None


@pytest.mark.asyncio
async def test_un_nouvel_eleve_ne_declenche_rien(db: Session) -> None:
    trouves, _ = await chercher_doublons(_Pont(db), last_name="ZOUZOUA", first_name="Emmanuella")
    assert trouves == []


@pytest.mark.asyncio
async def test_la_fiche_modifiee_ne_se_signale_pas_elle_meme(db: Session) -> None:
    trouves, _ = await chercher_doublons(
        _Pont(db),
        last_name="KOUASSI",
        first_name="David",
        enrollment_number="ECER0864",
        ignorer_student_id=2,
    )
    assert trouves == []


@pytest.mark.asyncio
async def test_une_faute_sur_la_premiere_lettre_est_rattrapee(db: Session) -> None:
    """COULIBALY saisi KOULIBALY doit rester detectable.

    Un prefixe strict defaisait la raison d'etre du score : le candidat n'etait
    jamais remonte, donc la ressemblance ne tournait meme pas. C'est pourtant
    exactement le cas pour lequel elle existe — une famille revient, le nom est
    tape d'oreille.
    """
    trouves, _ = await chercher_doublons(
        _Pont(db), last_name="KOULIBALY", first_name="Souleymane ben junior"
    )
    assert any(c.last_name == "COULIBALY" for c in trouves)


def test_le_motif_tolere_une_premiere_lettre_fausse() -> None:
    """Le prefiltre lui-meme, isole du reste.

    Le test ci-dessus passe aussi par le chemin du prenom : seul celui-ci
    prouve que la racine amputee est bien produite, et il tombe si on revient
    au prefixe strict.
    """
    # Un seul motif : le préfixe strict est contenu dans celui-ci, il ne
    # ramenait donc aucune ligne de plus.
    assert _motifs("KOULIBALY") == ["%ouli%"]
    # Trop court pour chercher quoi que ce soit sans tout remonter.
    assert _motifs("KO") == []


@pytest.mark.asyncio
async def test_une_apostrophe_ne_rend_pas_l_eleve_invisible(db: Session) -> None:
    """N'DRI figure dans le fichier des arrieres et doit se retrouver lui-meme.

    La normalisation Python remplacait l'apostrophe par une espace tandis que
    la colonne la gardait : aucun des deux motifs ne retrouvait l'autre, et cet
    eleve ne pouvait jamais etre signale comme doublon.

    L'apostrophe courbe est celle des claviers de telephone : elle a ete
    oubliee au premier correctif, qui ne traitait que la droite.
    """
    for saisie in ("N'DRI", "N’DRI", "NDRI", "N DRI"):
        trouves, _ = await chercher_doublons(
            _Pont(db), last_name=saisie, first_name="Etiakoun grace naomie"
        )
        assert any(c.last_name == "N'DRI" for c in trouves), f"« {saisie} » ne retrouve pas N'DRI"

    # L'autre sens : la fiche STOCKEE avec une apostrophe courbe. C'est celui
    # que le premier correctif laissait passer, parce qu'il ne nettoyait que la
    # saisie et pas la colonne.
    for saisie in ("N'GUESSAN", "NGUESSAN"):
        trouves, _ = await chercher_doublons(_Pont(db), last_name=saisie, first_name="Ama beatrice")
        assert any("GUESSAN" in c.last_name for c in trouves), (
            f"« {saisie} » ne retrouve pas la fiche stockee avec une apostrophe courbe"
        )


@pytest.mark.asyncio
async def test_deux_noms_etrangers_ne_se_rapprochent_pas(db: Session) -> None:
    """L'elargissement du prefiltre ne doit pas rapprocher n'importe quoi.

    Sans ce garde, tolerer une premiere lettre fausse deriverait vers un
    signalement permanent, et un avertissement permanent n'est plus lu.
    """
    trouves, _ = await chercher_doublons(_Pont(db), last_name="DIOMANDE", first_name="Sebe")
    assert all(c.last_name != "TRAORE" for c in trouves)


@pytest.mark.asyncio
async def test_le_nom_seul_ne_declenche_rien(db: Session) -> None:
    """Trois KOUASSI dans l'ecole : le nom seul rendrait 100 % pour chacun.

    C'est la saisie la plus frequente — la secretaire tape le nom avant le
    prenom. Signaler la ferait afficher « 100 % de ressemblance » a chaque
    inscription, et un avertissement permanent cesse d'etre lu.
    """
    trouves, _ = await chercher_doublons(_Pont(db), last_name="KOUASSI", first_name=None)
    assert trouves == []


@pytest.mark.asyncio
async def test_le_matricule_seul_signale_malgre_tout(db: Session) -> None:
    """L'exigence de preuve ne doit pas museler la certitude.

    Un matricule identique n'est pas une ressemblance : il ne passe pas par le
    score, et doit remonter meme sans prenom.
    """
    trouves, _ = await chercher_doublons(
        _Pont(db), last_name=None, first_name=None, enrollment_number="ECER0882"
    )
    assert [c.motif for c in trouves] == ["matricule"]


@pytest.mark.asyncio
async def test_la_troncature_est_annoncee(db: Session, monkeypatch) -> None:
    """« Rien trouvé » ne doit pas passer pour « on a tout regardé ».

    Le plafond de candidats peut couper avant le vrai doublon. Sans ce signal,
    le silence de l'écran ressemble à une certitude, sur un formulaire dont
    l'objet est d'empêcher une erreur à 2 287 000 FCFA.
    """
    from app.services.duplicates import detection

    monkeypatch.setattr(detection, "PLAFOND_CANDIDATS", 2)
    _, tronque = await chercher_doublons(
        _Pont(db), last_name="KOUASSI", first_name="Aya marie adelaide"
    )
    assert tronque is True


@pytest.mark.asyncio
async def test_sans_troncature_on_ne_le_pretend_pas(db: Session) -> None:
    _, tronque = await chercher_doublons(_Pont(db), last_name="TIOTE", first_name="Personne")
    assert tronque is False
