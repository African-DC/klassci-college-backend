"""Les noms qu'affiche le journal, vérifiés sur une vraie base.

Chaque test exécute les requêtes de `audit_labels` sur une base SQLite montée
depuis le schéma du modèle, et regarde le libellé produit. Aucun ne lit le
texte du code : un test qui vérifierait la forme d'une requête figerait son
écriture au lieu de vérifier ce qu'elle rend.
"""

from collections.abc import Iterator
from datetime import date, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, MetaData, column, create_engine, select, table
from sqlalchemy.orm import Session

from app.core.database import Base
from app.repositories import audit_labels
from app.repositories.audit_labels import Libelle
from app.services.audit.labels import page_labels

TOUT = None  # périmètre de l'accès complet
COMPTABLE = frozenset({"payment", "enrollment_fee", "fee_category", "cash_session"})


class _AsyncBridge:
    """L'allure d'une `AsyncSession`, sur une session synchrone : le code testé
    n'appelle qu'`execute`. Le compteur dit combien de requêtes une page coûte."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.requetes = 0

    async def execute(self, statement: object) -> object:
        self.requetes += 1
        return self._session.execute(statement)  # type: ignore[call-overload]


def _valeur_factice(colonne: Any) -> Any:
    """Une valeur quelconque pour une colonne obligatoire que le test ne regarde pas."""
    type_python = getattr(colonne.type, "python_type", str)
    enum = getattr(colonne.type, "enum_class", None) or getattr(
        getattr(colonne.type, "impl", None), "enum_class", None
    )
    if enum is not None:
        return next(iter(enum)).value
    return {
        int: 1,
        str: "x",
        bool: False,
        Decimal: Decimal("0"),
        date: date(2026, 9, 1),
        time: time(8, 0),
    }.get(type_python, "x")


def _inserer(engine: Engine, miroir: MetaData, table: str, **valeurs: Any) -> None:
    t = miroir.tables[table]
    for colonne in t.columns:
        manquante = colonne.name not in valeurs and not colonne.nullable
        sans_defaut = colonne.default is None and colonne.server_default is None
        if manquante and sans_defaut and not colonne.primary_key:
            try:
                valeurs[colonne.name] = _valeur_factice(colonne)
            except NotImplementedError:
                valeurs[colonne.name] = "x"
    with engine.begin() as conn:
        conn.execute(t.insert().values(**valeurs))


@pytest.fixture
def base() -> Iterator[tuple[_AsyncBridge, Engine, MetaData]]:
    """Une base neuve : une classe, un élève inscrit, un versement, une note."""
    miroir = MetaData()
    for modele in Base.metadata.tables.values():
        modele.to_metadata(miroir)
    engine = create_engine("sqlite://")
    # Toutes les tables : chaque type du registre doit pouvoir s'exécuter.
    miroir.create_all(engine)

    _inserer(engine, miroir, "levels", id=3, name="6e")
    _inserer(engine, miroir, "classes", id=12, name="6e B", level_id=3)
    _inserer(engine, miroir, "subjects", id=7, name="Mathématiques")
    _inserer(
        engine,
        miroir,
        "students",
        id=40,
        first_name="Aminata",
        last_name="Traoré",
        enrollment_number="CI-2026-0012",
    )
    _inserer(engine, miroir, "enrollments", id=42, student_id=40, class_id=12)
    _inserer(engine, miroir, "fee_categories", id=5, name="Scolarité")
    _inserer(engine, miroir, "enrollment_fees", id=9, enrollment_id=42, fee_category_id=5)
    _inserer(engine, miroir, "payments", id=88, enrollment_id=42, amount=Decimal("50000.00"))
    _inserer(engine, miroir, "evaluations", id=31, title="Devoir 1", subject_id=7, class_id=12)
    _inserer(engine, miroir, "grades", id=77, evaluation_id=31, student_id=40)
    _inserer(
        engine,
        miroir,
        "timetable_slots",
        id=60,
        class_id=12,
        subject_id=7,
        day="monday",
        start_time=time(8, 0),
        end_time=time(9, 0),
    )

    with Session(engine) as session:
        yield _AsyncBridge(session), engine, miroir


def _ligne(entity_type: str, entity_id: int, **champs: Any) -> Any:
    """Une ligne de journal : seuls ces attributs sont lus par le service."""
    return SimpleNamespace(
        entity_type=entity_type,
        entity_id=entity_id,
        subject_label=champs.get("subject_label"),
        old_values=champs.get("old_values"),
        new_values=champs.get("new_values"),
    )


@pytest.mark.parametrize("entity_type", sorted(audit_labels.LIBELLES))
@pytest.mark.asyncio
async def test_chaque_requete_du_registre_s_execute(base: Any, entity_type: str) -> None:
    """Une colonne mal nommée ne ferait pas planter la page : elle ferait
    disparaître les noms de son type, sans bruit. Ce test la fait échouer."""
    db, _, _ = base
    trouve = await audit_labels.names_by_type(db, {entity_type: [1]})
    assert entity_type in trouve


@pytest.mark.asyncio
async def test_chaque_type_se_nomme_comme_on_le_dit_au_guichet(base: Any) -> None:
    db, _, _ = base
    trouve = await audit_labels.names_by_type(
        db,
        {
            "class": [12],
            "level": [3],
            "student": [40],
            "enrollment": [42],
            "payment": [88],
            "grade": [77],
            "enrollment_fee": [9],
            "timetable_slot": [60],
        },
    )
    noms = {t: {i: f.nom for i, f in fiches.items()} for t, fiches in trouve.items()}
    assert noms["class"] == {12: "6e B"}
    assert noms["level"] == {3: "6e"}
    assert noms["student"] == {40: "Aminata Traoré · CI-2026-0012"}
    assert noms["enrollment"] == {42: "Aminata Traoré · 6e B"}
    assert noms["payment"] == {88: "50 000 FCFA · Aminata Traoré"}
    assert noms["grade"] == {77: "Aminata Traoré · Mathématiques"}
    assert noms["enrollment_fee"] == {9: "Scolarité"}
    # Le jour est stocké en anglais : l'écran le dit en français.
    assert noms["timetable_slot"] == {60: "6e B · Mathématiques · lundi · 08h00"}


@pytest.mark.asyncio
async def test_une_page_coute_une_requete_par_type_pas_une_par_ligne(base: Any) -> None:
    db, _, _ = base
    lignes = [_ligne("class", 12) for _ in range(40)] + [_ligne("student", 40) for _ in range(40)]
    await page_labels(db, lignes, allowed=TOUT)
    assert db.requetes == 2


@pytest.mark.asyncio
async def test_le_nom_fige_a_l_ecriture_l_emporte_sur_le_nom_actuel(base: Any) -> None:
    """« 6e A renommée en 6e B » se lit sous le nom qu'avait la classe alors."""
    db, _, _ = base
    fige = _ligne("class", 12, subject_label="6e A")
    ancienne = _ligne("class", 12)
    libelles = await page_labels(db, [fige, ancienne], allowed=TOUT)
    assert libelles.de(fige).nom == "6e A"
    assert libelles.de(ancienne).nom == "6e B"


@pytest.mark.asyncio
async def test_l_etat_de_la_fiche_distingue_active_archivee_supprimee(base: Any) -> None:
    """Une fiche archivée reste nommée, mais n'est pas proposée à l'ouverture.

    Sans la levée explicite du filtre d'archivage, l'élève archivé serait
    introuvable et passerait pour supprimé.
    """
    db, engine, miroir = base
    _inserer(
        engine,
        miroir,
        "students",
        id=41,
        first_name="Koffi",
        last_name="Yao",
        enrollment_number="CI-2026-0013",
        archived_at=date(2026, 9, 1),
    )
    presente = _ligne("class", 12)
    archivee = _ligne("student", 41)
    disparue = _ligne("class", 999)
    inconnue = _ligne("school_settings", 1)
    libelles = await page_labels(db, [presente, archivee, disparue, inconnue], allowed=TOUT)
    assert libelles.de(presente).etat == "active"
    assert libelles.de(archivee).etat == "archived"
    assert libelles.de(archivee).nom == "Koffi Yao · CI-2026-0013"
    assert libelles.de(disparue).etat == "deleted"
    assert libelles.de(disparue).nom is None
    # Un type qu'on ne sait pas chercher : aucun état, plutôt qu'un faux.
    assert libelles.de(inconnue).etat is None


@pytest.mark.asyncio
async def test_les_identifiants_des_valeurs_prennent_un_nom_sous_leur_cle(base: Any) -> None:
    """« Niveau : 6e » plutôt que « Niveau : 3 », y compris dans une répartition.

    Le nom est rangé sous la clé du champ : l'écran lit `slot_id:60` sans
    avoir à savoir que ce champ désigne un créneau.
    """
    db, _, _ = base
    modif = _ligne(
        "class",
        12,
        old_values={"level_id": 3, "slot_id": 60},
        new_values={"allocations": [{"enrollment_fee_id": 9, "amount": "20000"}]},
    )
    libelles = await page_labels(db, [modif], allowed=TOUT)
    assert libelles.de(modif).valeurs == {
        "level_id:3": "6e",
        "slot_id:60": "6e B · Mathématiques · lundi · 08h00",
        "enrollment_fee_id:9": "Scolarité",
    }


@pytest.mark.asyncio
async def test_un_perimetre_restreint_ne_lit_pas_de_nom_de_personne_dans_les_valeurs(
    base: Any,
) -> None:
    """Le comptable voit ses versements, pas les noms rangés dans leurs valeurs.

    Le versement lui-même reste nommé : son périmètre lui ouvre cette ligne.
    Mais un identifiant d'élève rangé dans une valeur ne doit pas devenir un
    second chemin vers des données que ce périmètre ne couvre pas.
    """
    db, _, _ = base
    versement = _ligne("payment", 88, new_values={"student_id": 40, "enrollment_fee_id": 9})
    libelles = await page_labels(db, [versement], allowed=COMPTABLE)
    assert libelles.de(versement).nom == "50 000 FCFA · Aminata Traoré"
    assert libelles.de(versement).valeurs == {"enrollment_fee_id:9": "Scolarité"}


@pytest.mark.asyncio
async def test_un_type_en_echec_ne_coute_que_ses_propres_noms(
    base: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La page s'affiche avec des numéros plutôt que de tomber en erreur, et
    une requête en échec ne fait pas dire « fiche supprimée »."""
    db, _, _ = base
    cassee = Libelle(
        requete=lambda ids: select(column("id")).select_from(table("inexistante")),
        former=lambda r: None,
    )
    monkeypatch.setitem(audit_labels.LIBELLES, "level", cassee)
    classe, niveau = _ligne("class", 12), _ligne("level", 3)
    libelles = await page_labels(db, [classe, niveau], allowed=TOUT)
    assert libelles.de(classe).nom == "6e B"
    assert libelles.de(niveau).nom is None
    assert libelles.de(niveau).etat is None
