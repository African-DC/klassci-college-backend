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
from app.services.duplicates.detection import _noyau, chercher_doublons


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
                    birth_date=date(2011, 1, 1),
                ),
                # Prenom proche du precedent : deux ressemblances, donc un ordre
                # entre elles a verifier.
                Student(
                    id=10,
                    last_name="KOUASSI",
                    first_name="Aya marie",
                    enrollment_number="ECER0905",
                    birth_date=date(2012, 2, 2),
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
                # Noms de trois lettres : parmi les plus repandus ici, et
                # invisibles tant que la recherche exigeait un fragment de
                # quatre caracteres.
                # Accent en MAJUSCULE : la table de repli ne se declenchait pas
                # sous SQLite, donc rien ne la couvrait.
                Student(
                    id=8,
                    last_name="KOUAMÉ",
                    # En MAJUSCULES : `ï` minuscule serait replie par la regle
                    # minuscule, que SQLite applique, et le test ne mesurerait
                    # alors pas la table majuscule.
                    first_name="AÏCHA",
                    enrollment_number="ECER0903",
                ),
                # Nom court AVEC apostrophe : seul le chemin de l'egalite peut
                # le retrouver, donc retirer la regle d'apostrophe se voit.
                Student(
                    id=9,
                    last_name="N'DA",
                    # Le prenom porte lui aussi une apostrophe : sinon la fiche
                    # remonte par ce chemin-la et la regle n'est pas eprouvee.
                    first_name="N'GO",
                    enrollment_number="ECER0904",
                ),
                Student(
                    id=7,
                    last_name="YAO",
                    first_name="Aya",
                    enrollment_number="ECER0902",
                    birth_date=date(2011, 5, 4),
                ),
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
    # Le matricule designe KOUASSI David, la saisie ressemble a KOUASSI Aya :
    # deux correspondances, donc un ordre a verifier. Avec une seule, l'ancienne
    # version etait vraie quoi qu'on fasse — le tri pouvait meme etre inverse.
    reponse = await chercher_doublons(
        _Pont(db),
        last_name="KOUASSI",
        first_name="Aya marie adelaide",
        enrollment_number="ECER0864",
    )
    assert reponse.correspondances[0].student_id == 2
    assert reponse.correspondances[0].motif == "matricule"
    # Et rien d'autre ne se glisse devant : les suivantes sont des
    # ressemblances, pas des certitudes.
    assert all(c.motif == "ressemblance" for c in reponse.correspondances[1:])
    assert len(reponse.correspondances) > 1, "il faut une suite pour vérifier une tête"


@pytest.mark.asyncio
async def test_sans_matricule_la_ressemblance_retrouve_la_fiche(db: Session) -> None:
    # La famille revient sans son papier : c'est le cas qui fabrique les
    # doublons, et celui que le score doit rattraper.
    reponse = await chercher_doublons(
        _Pont(db), last_name="Coulibaly", first_name="souleymane ben junior"
    )
    assert [t.student_id for t in reponse.correspondances] == [3]
    assert reponse.correspondances[0].motif == "ressemblance"
    assert reponse.correspondances[0].juge_sur_peu is True


@pytest.mark.asyncio
async def test_deux_kouassi_distincts_ne_sont_pas_confondus(db: Session) -> None:
    reponse = await chercher_doublons(_Pont(db), last_name="KOUASSI", first_name="David")
    assert [t.student_id for t in reponse.correspondances] == [2], (
        "l'autre KOUASSI a été signalé à tort"
    )


@pytest.mark.asyncio
async def test_une_inscription_non_validee_est_signalee(db: Session) -> None:
    # Le cœur de la demande : un dossier en attente ne se voit pas dans les
    # listes, et c'est celui-là qu'on recrée.
    reponse = await chercher_doublons(
        _Pont(db),
        last_name="KOUASSI",
        first_name="Aya marie adelaide",
        enrollment_number="ECER0882",
        academic_year_id=2,
    )
    inscription = reponse.correspondances[0].inscription_annee_courante
    assert inscription is not None
    # Le champ est un objet typé, plus un dictionnaire fourre-tout : une clé
    # mal orthographiée est désormais une erreur, pas un `None` silencieux.
    assert inscription.status == EnrollmentStatus.PROSPECT.value
    assert inscription.class_name == "3eme 2"


@pytest.mark.asyncio
async def test_sans_annee_on_ne_pretend_pas_connaitre_l_inscription(db: Session) -> None:
    reponse = await chercher_doublons(
        _Pont(db),
        last_name="KOUASSI",
        first_name="Aya marie adelaide",
        enrollment_number="ECER0882",
    )
    assert reponse.correspondances[0].inscription_annee_courante is None


@pytest.mark.asyncio
async def test_un_nouvel_eleve_ne_declenche_rien(db: Session) -> None:
    reponse = await chercher_doublons(_Pont(db), last_name="ZOUZOUA", first_name="Emmanuella")
    assert reponse.correspondances == []


@pytest.mark.asyncio
async def test_la_fiche_modifiee_ne_se_signale_pas_elle_meme(db: Session) -> None:
    reponse = await chercher_doublons(
        _Pont(db),
        last_name="KOUASSI",
        first_name="David",
        enrollment_number="ECER0864",
        ignorer_student_id=2,
    )
    assert reponse.correspondances == []


@pytest.mark.asyncio
async def test_une_faute_sur_la_premiere_lettre_est_rattrapee(db: Session) -> None:
    """COULIBALY saisi KOULIBALY doit rester detectable.

    Un prefixe strict defaisait la raison d'etre du score : le candidat n'etait
    jamais remonte, donc la ressemblance ne tournait meme pas. C'est pourtant
    exactement le cas pour lequel elle existe — une famille revient, le nom est
    tape d'oreille.
    """
    reponse = await chercher_doublons(
        _Pont(db), last_name="KOULIBALY", first_name="Souleymane ben junior"
    )
    assert any(c.last_name == "COULIBALY" for c in reponse.correspondances)


def test_le_motif_tolere_une_premiere_lettre_fausse() -> None:
    """Le prefiltre lui-meme, isole du reste.

    Le test ci-dessus passe aussi par le chemin du prenom : seul celui-ci
    prouve que la racine amputee est bien produite, et il tombe si on revient
    au prefixe strict.
    """
    # On cherche la racine privée de sa première lettre : c'est ce qui rattrape
    # la faute de frappe de tête.
    assert _noyau("KOULIBALY") == "oulib"
    # « YAO » donnerait « ao », qui remonte TRAORE et la moitié du fichier. Le
    # seuil porte sur le fragment réellement cherché, pas sur la racine avant
    # amputation.
    assert _noyau("YAO") is None
    assert _noyau("KO") is None


@pytest.mark.asyncio
async def test_une_apostrophe_ne_rend_pas_l_eleve_invisible(db: Session) -> None:
    """Les trois ecritures d'un meme nom doivent se retrouver.

    Droite, courbe, ou absente : la normalisation Python et celle du SQL
    doivent tomber d'accord. Ce test emprunte le motif flou, qui traverse
    l'apostrophe sans avoir besoin de la regle ; c'est
    `test_un_nom_court_avec_apostrophe_se_retrouve_sans` qui l'eprouve.
    """
    for saisie in ("N'DRI", "N’DRI", "NDRI", "N DRI"):
        reponse = await chercher_doublons(_Pont(db), last_name=saisie, first_name="Etiakoun")
        assert any(c.last_name == "N'DRI" for c in reponse.correspondances), (
            f"« {saisie} » ne retrouve pas N'DRI"
        )


@pytest.mark.asyncio
async def test_deux_noms_etrangers_ne_se_rapprochent_pas(db: Session) -> None:
    """L'elargissement du prefiltre ne doit pas rapprocher n'importe quoi.

    Sans ce garde, tolerer une premiere lettre fausse deriverait vers un
    signalement permanent, et un avertissement permanent n'est plus lu.
    """
    reponse = await chercher_doublons(_Pont(db), last_name="DIOMANDE", first_name="Sebe")
    # Assertion sur le résultat entier : la version précédente vérifiait que
    # TRAORE n'était pas là, alors qu'il n'était même pas candidat — elle
    # passait aussi avec le seuil de signalement ramené à zéro.
    assert reponse.correspondances == []


@pytest.mark.asyncio
async def test_le_nom_seul_ne_declenche_rien(db: Session) -> None:
    """Trois KOUASSI dans l'ecole : le nom seul rendrait 100 % pour chacun.

    C'est la saisie la plus frequente — la secretaire tape le nom avant le
    prenom. Signaler la ferait afficher « 100 % de ressemblance » a chaque
    inscription, et un avertissement permanent cesse d'etre lu.
    """
    reponse = await chercher_doublons(_Pont(db), last_name="KOUASSI", first_name=None)
    assert reponse.correspondances == []


@pytest.mark.asyncio
async def test_le_matricule_seul_signale_malgre_tout(db: Session) -> None:
    """L'exigence de preuve ne doit pas museler la certitude.

    Un matricule identique n'est pas une ressemblance : il ne passe pas par le
    score, et doit remonter meme sans prenom.
    """
    reponse = await chercher_doublons(
        _Pont(db), last_name=None, first_name=None, enrollment_number="ECER0882"
    )
    assert [c.motif for c in reponse.correspondances] == ["matricule"]


@pytest.mark.asyncio
async def test_la_troncature_est_annoncee(db: Session, monkeypatch) -> None:
    """« Rien trouvé » ne doit pas passer pour « on a tout regardé ».

    Le plafond de candidats peut couper avant le vrai doublon. Sans ce signal,
    le silence de l'écran ressemble à une certitude, sur un formulaire dont
    l'objet est d'empêcher une erreur à 2 287 000 FCFA.
    """
    from app.services.duplicates import detection

    monkeypatch.setattr(detection, "PLAFOND_CANDIDATS", 2)
    reponse = await chercher_doublons(
        _Pont(db), last_name="KOUASSI", first_name="Aya marie adelaide"
    )
    assert reponse.tronque is True


@pytest.mark.asyncio
async def test_sans_troncature_on_ne_le_pretend_pas(db: Session) -> None:
    reponse = await chercher_doublons(_Pont(db), last_name="TIOTE", first_name="Personne")
    assert reponse.tronque is False


@pytest.mark.asyncio
async def test_le_nom_seul_ne_touche_pas_la_base(db: Session) -> None:
    """Le garde de performance, épinglé par ce qu'il empêche vraiment.

    Le nom seul est l'état le plus fréquent du formulaire : la secrétaire le
    tape avant le prénom. Sans ce garde, chaque touche lançait quatre `LIKE` à
    joker de tête sur deux colonnes non indexées, pour un résultat que la règle
    de signalement interdisait de rapporter — sur la connexion d'une école.

    Les assertions sur le résultat ne suffisaient pas : elles restaient vertes
    parce que le filtrage aval faisait le travail. Celle-ci compte les requêtes.
    """
    pont = _Pont(db)
    appels = 0
    vrai_execute = pont.execute

    async def compte(*args, **kwargs):
        nonlocal appels
        appels += 1
        return await vrai_execute(*args, **kwargs)

    pont.execute = compte  # type: ignore[method-assign]

    await chercher_doublons(pont, last_name="KOUASSI", first_name=None)
    assert appels == 0, "le nom seul a interrogé la base pour rien"

    await chercher_doublons(pont, last_name="KOUASSI", first_name="Aya")
    assert appels == 1, "nom + prénom doit interroger la base"


@pytest.mark.asyncio
async def test_une_fiche_identique_aux_noms_courts_remonte(db: Session) -> None:
    """« YAO / Aya » : deux des noms les plus repandus ici.

    La recherche floue ampute la premiere lettre et exige trois caracteres
    restants, donc quatre au depart. « YAO » et « Aya » n'en ont que trois :
    aucune requete n'etait emise, et l'ecran annoncait « rien trouve » sur une
    fiche IDENTIQUE. On les cherche a l'identique plutot que pas du tout.
    """
    # Sans la date de naissance : elle est aussi une condition de la requete,
    # et la fournir ferait remonter la fiche par ce chemin-la. Le test ne
    # mesurerait alors pas ce qu'il annonce.
    reponse = await chercher_doublons(_Pont(db), last_name="YAO", first_name="Aya")
    assert [c.last_name for c in reponse.correspondances] == ["YAO"]


@pytest.mark.asyncio
async def test_l_egalite_sur_un_nom_court_ne_ratisse_pas_large(db: Session) -> None:
    """L'egalite ne doit pas se comporter comme « %ao% ».

    Un motif flou sur trois lettres remonterait TRAORE et une bonne part du
    fichier ; c'est pour cela qu'il etait refuse. L'egalite, elle, ne remonte
    que la fiche exacte.
    """
    reponse = await chercher_doublons(_Pont(db), last_name="YAO", first_name="Aya")
    assert all(c.last_name != "TRAORE" for c in reponse.correspondances)


@pytest.mark.asyncio
async def test_la_certitude_survit_au_plafond(db: Session, monkeypatch) -> None:
    """Un matricule exact ne doit jamais tomber sous la troncature.

    Le plafond garde les candidats par identifiant croissant. Une fiche récente
    portant le matricule saisi pouvait donc être évincée par des homonymes plus
    anciens : la seule correspondance certaine disparaissait, et l'écran
    n'affichait que des ressemblances.
    """
    from app.services.duplicates import detection

    monkeypatch.setattr(detection, "PLAFOND_CANDIDATS", 1)
    reponse = await chercher_doublons(
        _Pont(db),
        last_name="KOUASSI",
        first_name="Aya marie adelaide",
        enrollment_number="ECER0864",
    )
    # ECER0864 est KOUASSI David, identifiant 2 : sans le tri il serait derrière
    # KOUASSI Aya, identifiant 1, et le plafond de 1 l'éliminerait.
    assert [c.motif for c in reponse.correspondances] == ["matricule"]


@pytest.mark.asyncio
async def test_un_nom_accentue_se_retrouve_sans_accent(db: Session) -> None:
    """« KOUAME » doit retrouver « KOUAMÉ ».

    La table de repli des diacritiques n'etait couverte par rien : SQLite ne
    minuscule que l'ASCII, donc les regles ecrites en minuscules accentuees ne
    s'y declenchaient jamais. Les formes majuscules la rendent verifiable.
    """
    reponse = await chercher_doublons(_Pont(db), last_name="KOUAME", first_name="AICHA")
    assert any(c.last_name == "KOUAMÉ" for c in reponse.correspondances)


@pytest.mark.asyncio
async def test_un_nom_court_avec_apostrophe_se_retrouve_sans(db: Session) -> None:
    """« NDA » doit retrouver « N'DA ».

    Trois lettres : le motif flou ne s'applique pas, seule l'egalite peut le
    retrouver, et elle exige que l'apostrophe soit retiree des deux cotes.
    L'ancien test passait par « %dri% », qui traversait l'apostrophe sans avoir
    besoin de la regle.
    """
    reponse = await chercher_doublons(_Pont(db), last_name="NDA", first_name="NGO")
    assert any(c.last_name == "N'DA" for c in reponse.correspondances)


@pytest.mark.asyncio
async def test_la_date_de_naissance_elargit_la_recherche(db: Session) -> None:
    """La date ne dépend pas de l'orthographe : elle rattrape ce que le nom rate.

    Une interversion de lettres à l'intérieur du début du nom échappe au motif
    flou. La date, elle, est exacte ou fausse, et remonte la fiche quand même.
    """
    # Deux lettres interverties de chaque côté : « oauss » ne retrouve pas
    # « kouassi », « aamar » ne retrouve pas « ayamarie ». Aucun fragment ne
    # mène à la fiche ; seule la date la ramène, et le score la retient.
    reponse = await chercher_doublons(
        _Pont(db),
        last_name="KOAUSSI",
        first_name="Yaa marie",
        birth_date=date(2012, 2, 2),
    )
    assert any(c.enrollment_number == "ECER0905" for c in reponse.correspondances)


@pytest.mark.asyncio
async def test_les_ressemblances_sortent_de_la_plus_sure_a_la_moins_sure(db: Session) -> None:
    """Le second critère du tri, celui que le SQL ne fournit pas.

    `ORDER BY` place déjà la certitude en tête, mais rien en base ne connaît le
    score : c'est le tri Python qui range les ressemblances entre elles. Sans
    lui, l'écran met en avant la moins fiable des deux.
    """
    # La base rend les candidats par identifiant : 1 puis 10. Mais 10 ressemble
    # davantage à la saisie. Sans le tri Python, l'écran met le moins probable
    # en tête.
    reponse = await chercher_doublons(_Pont(db), last_name="KOUASSI", first_name="Aya marie")
    scores = [c.score for c in reponse.correspondances if c.score is not None]
    assert len(scores) >= 2, "il faut au moins deux ressemblances pour vérifier un ordre"
    assert scores == sorted(scores, reverse=True)
