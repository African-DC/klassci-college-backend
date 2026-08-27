"""Le remplissage de la migration 0075, exécuté sur de vraies lignes.

La CI joue `upgrade head` sur une base VIDE : la boucle de remplissage y itère
sur zéro fiche. Le seul morceau de la migration qui contienne de la logique
n'était donc exercé par rien, alors que c'est lui qui décide si les élèves déjà
inscrits restent trouvables après le déploiement.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from app.core.names import compact
from app.models.user import Student


def _charger_migration() -> ModuleType:
    """Importe la révision par son chemin : son nom de fichier commence par un chiffre."""
    chemin = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260827_0075_student_search_key.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0075", chemin)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Tampon:
    """Recueille le DDL rendu en mode hors ligne, ligne par ligne."""

    def __init__(self, lignes: list[str]) -> None:
        self._lignes = lignes

    def write(self, texte: str) -> None:
        self._lignes.append(texte)

    def flush(self) -> None:
        return None


@pytest.mark.parametrize(
    ("nom", "prenom", "cle_nom", "cle_prenom"),
    [
        ("N’GUESSAN", "Marie-Line", "nguessan", "marieline"),
        ("KOUAMÉ", "Aïcha", "kouame", "aicha"),
        ("TRAORÉ", "Sœur Anne", "traore", "soeuranne"),
    ],
)
def test_les_fiches_existantes_recoivent_la_meme_cle_que_les_futures(
    nom: str, prenom: str, cle_nom: str, cle_prenom: str
) -> None:
    """Une fiche d'hier doit répondre exactement comme une fiche de demain.

    L'attendu n'est pas un littéral écrit à la main : c'est la clé que le
    MODÈLE produirait pour le même nom. Une version antérieure comparait à des
    littéraux, et restait donc verte si le remplissage et le validateur
    divergeaient — c'est-à-dire dans le seul cas qu'elle prétendait exclure.
    """
    migration = _charger_migration()
    moteur = create_engine("sqlite://")
    with moteur.begin() as connexion:
        connexion.execute(
            text(
                "CREATE TABLE students (id INTEGER PRIMARY KEY, last_name TEXT, "
                "first_name TEXT, last_name_key TEXT DEFAULT '', first_name_key TEXT DEFAULT '')"
            )
        )
        connexion.execute(
            text("INSERT INTO students (id, last_name, first_name) VALUES (1, :n, :p)"),
            {"n": nom, "p": prenom},
        )

        migration._remplir(connexion)

        obtenu = connexion.execute(
            text("SELECT last_name_key, first_name_key FROM students WHERE id = 1")
        ).one()
    fiche_neuve = Student(last_name=nom, first_name=prenom)
    assert obtenu == (fiche_neuve.last_name_key, fiche_neuve.first_name_key), (
        "le remplissage doit produire la meme cle que le validateur du modele"
    )
    # Les valeurs attendues sont aussi epinglees en clair : sans cela, les
    # deux cotes pourraient deriver ensemble sans que rien ne le voie.
    assert obtenu == (cle_nom, cle_prenom)


def test_le_remplissage_ne_touche_pas_une_base_vide() -> None:
    """Le cas de la CI et de tout nouvel établissement : aucune fiche à reprendre."""
    migration = _charger_migration()
    moteur = create_engine("sqlite://")
    with moteur.begin() as connexion:
        connexion.execute(
            text(
                "CREATE TABLE students (id INTEGER PRIMARY KEY, last_name TEXT, "
                "first_name TEXT, last_name_key TEXT DEFAULT '', first_name_key TEXT DEFAULT '')"
            )
        )
        migration._remplir(connexion)
        assert connexion.execute(text("SELECT COUNT(*) FROM students")).scalar_one() == 0


def test_le_defaut_serveur_est_retire_apres_le_remplissage(monkeypatch) -> None:
    """Sans ce retrait, un INSERT sans clé réussirait en silence.

    C'est le seul mécanisme structurel contre le mode de panne que tout ce
    travail cherche à rendre impossible : un élève enregistré avec une clé vide
    est invisible à la détection, donc recréable en double, avec une seconde
    ardoise que personne ne rapproche de la première. Le commentaire du modèle
    fait reposer sur ce retrait la phrase « un INSERT sans clé échoue durement ».

    Le DDL est celui que produirait MySQL, pas une lecture du fichier source.
    Le remplissage est neutralisé ici parce qu'il ne peut pas lire de lignes
    sans connexion ; il a ses propres tests juste au-dessus.
    """
    migration = _charger_migration()
    monkeypatch.setattr(migration, "_remplir", lambda _connexion: None)

    lignes: list[str] = []
    contexte = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": _Tampon(lignes)}
    )
    with Operations.context(contexte):
        migration.upgrade()
    ddl = " ".join(lignes).upper()

    for colonne in ("LAST_NAME_KEY", "FIRST_NAME_KEY"):
        assert f"ALTER COLUMN {colonne} DROP DEFAULT" in ddl, (
            f"le defaut serveur de {colonne} doit etre retire apres le remplissage"
        )
    # L'ordre compte : retirer le defaut AVANT d'ajouter la colonne ferait
    # echouer l'ALTER TABLE sur les lignes existantes.
    assert ddl.index("ADD COLUMN LAST_NAME_KEY") < ddl.index("ALTER COLUMN LAST_NAME_KEY DROP")


def test_la_migration_refuse_le_mode_hors_ligne() -> None:
    """`alembic upgrade --sql` produirait un script qui perd toutes les fiches.

    Le DDL seul poserait les colonnes avec une chaîne vide et n'irait jamais
    lire les élèves existants : tout le fichier deviendrait invisible à la
    détection, sans un mot. Refuser est le seul comportement honnête.
    """
    migration = _charger_migration()
    contexte = MigrationContext.configure(
        dialect_name="mysql", opts={"as_sql": True, "output_buffer": _Tampon([])}
    )
    with Operations.context(contexte), pytest.raises(RuntimeError, match="hors ligne"):
        migration.upgrade()


def test_la_largeur_de_la_cle_absorbe_le_pire_nom() -> None:
    """La colonne doit tenir le nom le plus long que le modèle accepte.

    `compact()` peut allonger : une ligature devient deux lettres. La marge est
    nulle — cent « oe » ligaturés produisent exactement 200 caractères pour une
    colonne de 200. Élargir `last_name`, ou ajouter une substitution qui
    remplace un caractère par trois, casserait l'invariant en silence : MySQL
    tronquerait la clé, et l'élève deviendrait introuvable sous son vrai nom.

    La largeur est aussi écrite à deux endroits — le modèle et la migration.
    Ce test les compare : elles ne peuvent plus diverger sans bruit.
    """
    migration = _charger_migration()
    colonne_modele = Student.__table__.columns["last_name_key"]
    assert colonne_modele.type.length == migration._LARGEUR, (
        "le modèle et la migration doivent déclarer la même largeur"
    )

    nom_maximal = Student.__table__.columns["last_name"].type.length
    pire_nom = "œ" * nom_maximal
    assert len(compact(pire_nom)) <= migration._LARGEUR, (
        f"un nom de {nom_maximal} caractères doit tenir dans la clé"
    )
