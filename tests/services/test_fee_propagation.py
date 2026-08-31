"""Répercuter un tarif corrigé sur les dettes déjà écrites, sans casser les reçus.

Une école saisit 54 000 pour la Scolarité T1, inscrit trois cents élèves, puis
s'aperçoit que le tarif voté était 45 000. Jusqu'ici, corriger la grille ne
changeait rien aux dettes : les familles continuaient de devoir l'ancien
montant, et personne ne le disait.

Les tests tournent sur SQLite, via le module standard : ils exécutent le vrai
SQL du service, sans base MySQL à provisionner. Ils appellent les fonctions et
regardent ce qu'elles produisent en base, jamais leur code source : le seul
verrou qui vaille est celui qui casse quand le comportement change.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.database import Base
from app.core.exceptions import NotFoundError
from app.models.academic import Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeCategory,
    FeeEnrollmentProfile,
    FeeVariant,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentStatus,
)
from app.services import fee_propagation

AY = 2026
AY_PRECEDENTE = 2025
LEVEL_6E = 10
CLASSE_6E_A = 1

CAT_SCOLARITE_T1 = 100
CAT_TENUE = 101
CAT_CHEMISE = 102

TARIF_T1 = 1
TARIF_TENUE = 2
TARIF_CHEMISE_NOUVEAU = 3

MONTANT_CHEMISE = Decimal("3000.00")

ANCIEN_MONTANT = Decimal("54000.00")
NOUVEAU_MONTANT = Decimal("45000.00")

CAISSIERE = 7


class _AsyncBridge:
    """Donne l'allure d'une `AsyncSession` à une session SQLAlchemy synchrone.

    Le service n'utilise que ces gestes ; les envelopper évite d'ajouter un
    pilote asynchrone à la seule fin de faire tourner des tests.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    async def execute(self, statement: object) -> object:
        return self.session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self.session.add(instance)

    async def flush(self) -> None:
        self.session.flush()


def _sqlite_schema() -> list[Table]:
    """Le schéma des tables utiles, transposé pour SQLite.

    SQLite ne numérote automatiquement que les colonnes déclarées
    « INTEGER PRIMARY KEY » : les `BIGINT` du modèle refuseraient tout INSERT
    sans identifiant. On travaille sur une copie du schéma, jamais sur les
    tables du modèle, que les autres tests lisent.
    """
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)

    utiles = []
    for nom in (
        "classes",
        "fee_categories",
        "fee_variants",
        "enrollments",
        "enrollment_fees",
        "payments",
        "payment_allocations",
        "audit_logs",
    ):
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        utiles.append(table)
    return utiles


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    """Une base neuve par test, avec les catégories et les deux tarifs."""
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Class(id=CLASSE_6E_A, name="6eme A", level_id=LEVEL_6E),
                FeeCategory(id=CAT_SCOLARITE_T1, name="Scolarite T1", is_mandatory=True),
                FeeCategory(id=CAT_TENUE, name="Tenue", is_mandatory=True),
                FeeCategory(id=CAT_CHEMISE, name="Chemise cartonnee", is_mandatory=True),
                # Le tarif porte déjà la correction : c'est l'écran des frais
                # qui vient de l'enregistrer, les dettes n'ont pas suivi.
                FeeVariant(
                    id=TARIF_T1,
                    fee_category_id=CAT_SCOLARITE_T1,
                    academic_year_id=AY,
                    amount=NOUVEAU_MONTANT,
                    level_id=LEVEL_6E,
                ),
                FeeVariant(
                    id=TARIF_TENUE,
                    fee_category_id=CAT_TENUE,
                    academic_year_id=AY,
                    amount=Decimal("15000.00"),
                    level_id=LEVEL_6E,
                ),
                # Le tarif que l'école vient d'ajouter après la rentrée : aucune
                # inscription ne le porte encore.
                FeeVariant(
                    id=TARIF_CHEMISE_NOUVEAU,
                    fee_category_id=CAT_CHEMISE,
                    academic_year_id=AY,
                    amount=MONTANT_CHEMISE,
                    level_id=LEVEL_6E,
                    enrollment_profile=FeeEnrollmentProfile.NOUVEAU,
                ),
            ]
        )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


# ---------------------------------------------------------------------------
# Fabrication des situations d'école
# ---------------------------------------------------------------------------


def _inscrire(
    db: _AsyncBridge,
    enrollment_id: int,
    *,
    annee: int = AY,
    statut: EnrollmentStatus = EnrollmentStatus.VALIDE,
    archivee: bool = False,
    profil: bool | None = None,
) -> None:
    db.session.add(
        Enrollment(
            id=enrollment_id,
            student_id=enrollment_id,
            class_id=CLASSE_6E_A,
            academic_year_id=annee,
            status=statut,
            is_new_student=profil,
            archived_at=datetime.now(UTC) if archivee else None,
        )
    )
    db.session.flush()


def _facturer(
    db: _AsyncBridge,
    fee_id: int,
    enrollment_id: int,
    *,
    variant_id: int = TARIF_T1,
    category_id: int = CAT_SCOLARITE_T1,
    montant: Decimal = ANCIEN_MONTANT,
    statut: EnrollmentFeeStatus = EnrollmentFeeStatus.PENDING,
) -> None:
    db.session.add(
        EnrollmentFee(
            id=fee_id,
            enrollment_id=enrollment_id,
            fee_variant_id=variant_id,
            fee_category_id=category_id,
            amount=montant,
            status=statut,
        )
    )
    db.session.flush()


def _verser(db: _AsyncBridge, payment_id: int, fee_id: int, montant: str) -> None:
    """Un versement encaissé, imputé sur ce frais. La caisse l'a compté."""
    db.session.add(
        Payment(
            id=payment_id,
            enrollment_id=None,
            amount=Decimal(montant),
            method=PaymentMethod.CASH,
            status=PaymentStatus.COMPLETED,
        )
    )
    db.session.flush()
    db.session.add(
        PaymentAllocation(
            id=payment_id,
            payment_id=payment_id,
            enrollment_fee_id=fee_id,
            amount=Decimal(montant),
        )
    )
    db.session.flush()


def _montant(db: _AsyncBridge, fee_id: int) -> Decimal:
    ligne = db.session.get(EnrollmentFee, fee_id)
    assert ligne is not None
    return Decimal(str(ligne.amount))


async def _apercu(db: _AsyncBridge, variant_id: int = TARIF_T1) -> object:
    return await fee_propagation.preview_variant_propagation(db, variant_id)  # type: ignore[arg-type]


async def _confirmer(db: _AsyncBridge, variant_id: int = TARIF_T1) -> object:
    return await fee_propagation.apply_variant_propagation(
        db,  # type: ignore[arg-type]
        variant_id,
        applied_by=CAISSIERE,
    )


# ---------------------------------------------------------------------------
# Ce que la répercussion fait, et ne fait pas
# ---------------------------------------------------------------------------


async def test_une_ligne_non_payee_prend_le_nouveau_montant(db: _AsyncBridge) -> None:
    """Le cas nominal : la famille n'a rien versé, sa dette suit la correction."""
    _inscrire(db, 1)
    _facturer(db, 11, 1)

    resultat = await _confirmer(db)

    assert _montant(db, 11) == NOUVEAU_MONTANT
    assert resultat.fees_updated == 1  # type: ignore[attr-defined]
    assert resultat.debt_delta == NOUVEAU_MONTANT - ANCIEN_MONTANT  # type: ignore[attr-defined]


async def test_une_ligne_portant_un_versement_reste_intacte(db: _AsyncBridge) -> None:
    """La règle d'or : de l'argent est imputé ici, on n'y touche pas.

    Réécrire ce montant ferait mentir le reçu que la famille a en main, et
    pourrait rendre le reste dû négatif si elle avait déjà tout soldé.
    """
    _inscrire(db, 1)
    _facturer(db, 11, 1)
    _verser(db, 500, 11, "20000.00")

    resultat = await _confirmer(db)

    assert _montant(db, 11) == ANCIEN_MONTANT
    assert resultat.fees_updated == 0  # type: ignore[attr-defined]
    assert resultat.fees_kept_with_payments == 1  # type: ignore[attr-defined]
    assert resultat.debt_delta == Decimal("0")  # type: ignore[attr-defined]


async def test_l_apercu_annonce_exactement_ce_que_la_confirmation_fera(
    db: _AsyncBridge,
) -> None:
    """Un aperçu qui annonce autre chose que le geste ne sert qu'à rassurer.

    Trois situations mêlées, telles qu'une école les a réellement : deux
    familles qui n'ont rien versé, une qui a déjà payé, une ligne déjà
    corrigée à la main, une exonérée.
    """
    for enrollment_id, fee_id in ((1, 11), (2, 12)):
        _inscrire(db, enrollment_id)
        _facturer(db, fee_id, enrollment_id)

    _inscrire(db, 3)
    _facturer(db, 13, 3)
    _verser(db, 500, 13, "10000.00")

    _inscrire(db, 4)
    _facturer(db, 14, 4, montant=NOUVEAU_MONTANT)

    _inscrire(db, 5)
    _facturer(db, 15, 5, statut=EnrollmentFeeStatus.WAIVED)

    apercu = await _apercu(db)
    resultat = await _confirmer(db)

    assert apercu.fees_to_update == resultat.fees_updated == 2  # type: ignore[attr-defined]
    assert apercu.enrollments_concerned == resultat.enrollments_concerned == 5  # type: ignore[attr-defined]
    assert apercu.fees_kept_with_payments == resultat.fees_kept_with_payments == 1  # type: ignore[attr-defined]
    assert apercu.fees_already_up_to_date == resultat.fees_already_up_to_date == 1  # type: ignore[attr-defined]
    assert apercu.fees_waived == resultat.fees_waived == 1  # type: ignore[attr-defined]
    assert apercu.debt_delta == resultat.debt_delta  # type: ignore[attr-defined]


async def test_les_cinq_paquets_totalisent_les_inscriptions_concernees(
    db: _AsyncBridge,
) -> None:
    """Un total que son propre détail contredit fait douter de tout l'écran.

    Les cinq situations mêlées, dont la cinquième : une inscription qui ne
    porte aucune ligne de cette catégorie et devrait en recevoir une.
    """
    _inscrire(db, 1)
    _facturer(db, 11, 1)
    _inscrire(db, 2)
    _facturer(db, 12, 2)
    _verser(db, 500, 12, "5000.00")
    _inscrire(db, 3)
    _facturer(db, 13, 3, montant=NOUVEAU_MONTANT)
    _inscrire(db, 4)
    _facturer(db, 14, 4, statut=EnrollmentFeeStatus.WAIVED)
    _inscrire(db, 5)  # jamais facturée de Scolarité T1

    apercu = await _apercu(db)

    somme = (
        apercu.fees_to_update  # type: ignore[attr-defined]
        + apercu.fees_to_create  # type: ignore[attr-defined]
        + apercu.fees_kept_with_payments  # type: ignore[attr-defined]
        + apercu.fees_already_up_to_date  # type: ignore[attr-defined]
        + apercu.fees_waived  # type: ignore[attr-defined]
    )
    assert apercu.fees_to_create == 1  # type: ignore[attr-defined]
    assert somme == apercu.enrollments_concerned == 5  # type: ignore[attr-defined]


async def test_refuser_ne_change_rien(db: _AsyncBridge) -> None:
    """Lire l'impact et dire non doit laisser la base exactement comme avant."""
    _inscrire(db, 1)
    _facturer(db, 11, 1)
    _inscrire(db, 2)
    _facturer(db, 12, 2)

    await _apercu(db)
    await _apercu(db)

    assert _montant(db, 11) == ANCIEN_MONTANT
    assert _montant(db, 12) == ANCIEN_MONTANT
    assert db.session.execute(select(AuditLog)).scalars().all() == []


# ---------------------------------------------------------------------------
# Le périmètre : ce tarif, cette année, ces inscriptions
# ---------------------------------------------------------------------------


async def test_une_inscription_d_une_autre_annee_n_est_pas_touchee(db: _AsyncBridge) -> None:
    """Sa facture a été émise sous une autre grille, elle reste vraie."""
    _inscrire(db, 1)
    _facturer(db, 11, 1)
    _inscrire(db, 2, annee=AY_PRECEDENTE)
    _facturer(db, 12, 2)

    resultat = await _confirmer(db)

    assert _montant(db, 11) == NOUVEAU_MONTANT
    assert _montant(db, 12) == ANCIEN_MONTANT
    assert resultat.enrollments_concerned == 1  # type: ignore[attr-defined]


async def test_un_autre_tarif_de_la_meme_annee_n_est_pas_touche(db: _AsyncBridge) -> None:
    """Ajuster le prix de la tenue ne doit pas rejouer la scolarité."""
    _inscrire(db, 1)
    _facturer(db, 11, 1)
    _facturer(
        db,
        12,
        1,
        variant_id=TARIF_TENUE,
        category_id=CAT_TENUE,
        montant=Decimal("12000.00"),
    )

    await _confirmer(db, TARIF_TENUE)

    assert _montant(db, 11) == ANCIEN_MONTANT
    assert _montant(db, 12) == Decimal("15000.00")


async def test_une_inscription_archivee_n_est_pas_touchee(db: _AsyncBridge) -> None:
    """La corbeille garde les fiches telles qu'elles y sont entrées.

    La garantie vient du filtre pose sur la session, pas d'une clause ecrite
    dans ce service. On la verifie quand meme ici : ce qui compte pour l'ecole
    est que la dette d'une fiche archivee ne bouge pas, peu importe la couche
    qui l'en empeche.
    """
    _inscrire(db, 1, archivee=True)
    _facturer(db, 11, 1)

    resultat = await _confirmer(db)

    assert _montant(db, 11) == ANCIEN_MONTANT
    assert resultat.enrollments_concerned == 0  # type: ignore[attr-defined]
    assert "rien à répercuter" in resultat.message  # type: ignore[attr-defined]


async def test_une_inscription_annulee_n_est_pas_touchee(db: _AsyncBridge) -> None:
    """Relancer à la hausse la dette d'un dossier clos rouvrirait un impayé."""
    _inscrire(db, 1, statut=EnrollmentStatus.ANNULE)
    _facturer(db, 11, 1)

    resultat = await _confirmer(db)

    assert _montant(db, 11) == ANCIEN_MONTANT
    assert resultat.enrollments_concerned == 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Le chiffre montré à l'école
# ---------------------------------------------------------------------------


async def test_l_ecart_de_dette_ignore_les_lignes_conservees(db: _AsyncBridge) -> None:
    """L'écart annoncé est celui des seules lignes réécrites.

    Compter aussi les lignes conservées gonflerait un chiffre que la
    comptabilité ne retrouvera jamais dans ses comptes.
    """
    for enrollment_id, fee_id in ((1, 11), (2, 12)):
        _inscrire(db, enrollment_id)
        _facturer(db, fee_id, enrollment_id)
    _inscrire(db, 3)
    _facturer(db, 13, 3)
    _verser(db, 500, 13, "1000.00")

    apercu = await _apercu(db)

    assert apercu.debt_delta == 2 * (NOUVEAU_MONTANT - ANCIEN_MONTANT)  # type: ignore[attr-defined]
    assert apercu.debt_delta < 0  # type: ignore[attr-defined]


async def test_une_hausse_de_tarif_rend_un_ecart_positif(db: _AsyncBridge) -> None:
    """Le tarif voté était plus élevé que celui saisi : la dette monte."""
    _inscrire(db, 1)
    _facturer(db, 11, 1, montant=Decimal("30000.00"))

    apercu = await _apercu(db)

    assert apercu.debt_delta == Decimal("15000.00")  # type: ignore[attr-defined]
    assert "augmenterait de 15 000 F" in apercu.message  # type: ignore[attr-defined]


async def test_repercuter_deux_fois_ne_change_plus_rien(db: _AsyncBridge) -> None:
    """Le second passage doit être un geste vide, pas un second écart."""
    _inscrire(db, 1)
    _facturer(db, 11, 1)

    await _confirmer(db)
    second = await _confirmer(db)

    assert _montant(db, 11) == NOUVEAU_MONTANT
    assert second.fees_updated == 0  # type: ignore[attr-defined]
    assert second.fees_already_up_to_date == 1  # type: ignore[attr-defined]
    assert second.debt_delta == Decimal("0")  # type: ignore[attr-defined]


async def test_l_apercu_nomme_la_categorie(db: _AsyncBridge) -> None:
    """L'école doit relire le nom du frais qu'elle s'apprête à répercuter."""
    _inscrire(db, 1)
    _facturer(db, 11, 1)

    apercu = await _apercu(db)

    assert apercu.category_name == "Scolarite T1"  # type: ignore[attr-defined]
    assert apercu.fee_category_id == CAT_SCOLARITE_T1  # type: ignore[attr-defined]
    assert apercu.amount == NOUVEAU_MONTANT  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# La trace
# ---------------------------------------------------------------------------


async def test_l_acte_est_journalise_avec_son_auteur(db: _AsyncBridge) -> None:
    """Une dette qui bouge sans qu'on sache qui l'a bougée est ingérable."""
    _inscrire(db, 1)
    _facturer(db, 11, 1)

    await _confirmer(db)

    entrees = db.session.execute(select(AuditLog)).scalars().all()
    assert len(entrees) == 1
    entree = entrees[0]
    assert entree.user_id == CAISSIERE
    assert entree.entity_type == "fee_variant"
    assert entree.entity_id == TARIF_T1
    assert entree.new_values is not None
    assert entree.new_values["action"] == "propagate_to_enrollments"
    assert entree.new_values["fees_updated"] == 1
    assert entree.new_values["fee_category_id"] == CAT_SCOLARITE_T1


async def test_un_tarif_inconnu_est_refuse(db: _AsyncBridge) -> None:
    """Mieux vaut un 404 lisible qu'une répercussion sur zéro ligne."""
    with pytest.raises(NotFoundError):
        await _apercu(db, 9999)
    with pytest.raises(NotFoundError):
        await _confirmer(db, 9999)


# ---------------------------------------------------------------------------
# Le cinquième paquet : les lignes qui manquent
# ---------------------------------------------------------------------------


def _lignes_de(db: _AsyncBridge, enrollment_id: int, category_id: int) -> list[EnrollmentFee]:
    return (
        db.session.query(EnrollmentFee)
        .filter(
            EnrollmentFee.enrollment_id == enrollment_id,
            EnrollmentFee.fee_category_id == category_id,
        )
        .all()
    )


async def _apercu_chemise(db: _AsyncBridge) -> object:
    return await _apercu(db, TARIF_CHEMISE_NOUVEAU)


async def test_le_tarif_nouveau_atteint_les_nouveaux_deja_inscrits(db: _AsyncBridge) -> None:
    """L'école ajoute la chemise cartonnée après la rentrée. Ressaisir six
    cents dossiers à la main n'est pas une option."""
    _inscrire(db, 1, profil=True)

    resultat = await _confirmer(db, TARIF_CHEMISE_NOUVEAU)

    lignes = _lignes_de(db, 1, CAT_CHEMISE)
    assert len(lignes) == 1
    assert Decimal(str(lignes[0].amount)) == MONTANT_CHEMISE
    assert resultat.fees_created == 1  # type: ignore[attr-defined]


async def test_un_ancien_ne_recoit_pas_le_tarif_nouveau(db: _AsyncBridge) -> None:
    """Il a déjà payé sa chemise l'an dernier."""
    _inscrire(db, 1, profil=False)

    resultat = await _confirmer(db, TARIF_CHEMISE_NOUVEAU)

    assert _lignes_de(db, 1, CAT_CHEMISE) == []
    assert resultat.fees_created == 0  # type: ignore[attr-defined]


async def test_une_inscription_sans_profil_ne_recoit_pas_le_tarif_nouveau(
    db: _AsyncBridge,
) -> None:
    """L'invariant tenu jusqu'ici : personne ne tranche à la place de l'école,
    pas même une répercussion en masse. C'est le chemin par lequel le collège
    Rostan facturerait la chemise à tous ses anciens élèves d'un seul clic."""
    _inscrire(db, 1, profil=None)

    resultat = await _confirmer(db, TARIF_CHEMISE_NOUVEAU)

    assert _lignes_de(db, 1, CAT_CHEMISE) == []
    assert resultat.enrollments_concerned == 0  # type: ignore[attr-defined]


async def test_une_ligne_deja_portee_n_est_pas_recreee(db: _AsyncBridge) -> None:
    """Sinon on refabriquerait le doublon que `uq_enrollment_fee_category`
    existe pour interdire, et la dette de la famille doublerait."""
    _inscrire(db, 1, profil=True)
    _facturer(
        db,
        21,
        1,
        variant_id=TARIF_CHEMISE_NOUVEAU,
        category_id=CAT_CHEMISE,
        montant=MONTANT_CHEMISE,
    )

    resultat = await _confirmer(db, TARIF_CHEMISE_NOUVEAU)

    assert len(_lignes_de(db, 1, CAT_CHEMISE)) == 1
    assert resultat.fees_created == 0  # type: ignore[attr-defined]
    assert resultat.fees_already_up_to_date == 1  # type: ignore[attr-defined]


async def test_une_inscription_annulee_ne_recoit_pas_de_ligne_neuve(db: _AsyncBridge) -> None:
    """Son dossier est clos : lui rouvrir un impayé serait un contresens."""
    _inscrire(db, 1, profil=True, statut=EnrollmentStatus.ANNULE)

    resultat = await _confirmer(db, TARIF_CHEMISE_NOUVEAU)

    assert _lignes_de(db, 1, CAT_CHEMISE) == []
    assert resultat.fees_created == 0  # type: ignore[attr-defined]


async def test_une_inscription_archivee_ne_recoit_pas_de_ligne_neuve(db: _AsyncBridge) -> None:
    """La corbeille garde les fiches telles qu'elles y sont entrées."""
    _inscrire(db, 1, profil=True, archivee=True)

    resultat = await _confirmer(db, TARIF_CHEMISE_NOUVEAU)

    assert resultat.fees_created == 0  # type: ignore[attr-defined]


async def test_l_apercu_annonce_les_creations_avant_de_les_faire(db: _AsyncBridge) -> None:
    """Un aperçu qui annonce autre chose que le geste ne sert qu'à rassurer."""
    _inscrire(db, 1, profil=True)
    _inscrire(db, 2, profil=True)
    _inscrire(db, 3, profil=False)

    apercu = await _apercu_chemise(db)
    resultat = await _confirmer(db, TARIF_CHEMISE_NOUVEAU)

    assert apercu.fees_to_create == resultat.fees_created == 2  # type: ignore[attr-defined]
    assert "2 lignes à créer" in apercu.message  # type: ignore[attr-defined]
    assert "2 lignes créées" in resultat.message  # type: ignore[attr-defined]


async def test_l_apercu_ne_cree_rien(db: _AsyncBridge) -> None:
    """Lire l'impact et dire non doit laisser la base exactement comme avant."""
    _inscrire(db, 1, profil=True)

    await _apercu_chemise(db)

    assert _lignes_de(db, 1, CAT_CHEMISE) == []


async def test_la_dette_creee_entre_dans_l_ecart_annonce(db: _AsyncBridge) -> None:
    """Annoncer « la dette ne bouge pas » en créant deux cents lignes serait
    exactement le total que son propre détail contredit."""
    _inscrire(db, 1, profil=True)
    _inscrire(db, 2, profil=True)

    apercu = await _apercu_chemise(db)

    assert apercu.debt_delta == 2 * MONTANT_CHEMISE  # type: ignore[attr-defined]


async def test_repercuter_deux_fois_ne_recree_rien(db: _AsyncBridge) -> None:
    """Le second passage doit être un geste vide, pas une seconde chemise."""
    _inscrire(db, 1, profil=True)

    await _confirmer(db, TARIF_CHEMISE_NOUVEAU)
    second = await _confirmer(db, TARIF_CHEMISE_NOUVEAU)

    assert len(_lignes_de(db, 1, CAT_CHEMISE)) == 1
    assert second.fees_created == 0  # type: ignore[attr-defined]


async def test_une_inscription_d_une_autre_annee_ne_recoit_pas_de_ligne_neuve(
    db: _AsyncBridge,
) -> None:
    """Sa facture a été émise sous une autre grille, elle reste vraie."""
    _inscrire(db, 1, profil=True, annee=AY_PRECEDENTE)

    resultat = await _confirmer(db, TARIF_CHEMISE_NOUVEAU)

    assert _lignes_de(db, 1, CAT_CHEMISE) == []
    assert resultat.fees_created == 0  # type: ignore[attr-defined]
