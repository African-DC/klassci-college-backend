"""La 0084 s'arrête AVANT toute écriture quand une inscription porte deux bourses.

MySQL valide chaque DDL : un index refusé après les ajouts de colonnes
laisserait une base à moitié migrée. La révision vérifie donc d'abord, et pose
l'index avant les colonnes. Ce qui est éprouvé ici : le refus, son message, et
qu'aucune colonne n'a été ajoutée. La pose réelle sur MySQL relève de la CI.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _migration() -> ModuleType:
    chemin = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261001_0084_enrollment_information_sheet.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0084", chemin)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base(bourses: list[tuple[int, int]]):
    moteur = create_engine("sqlite://")
    with moteur.begin() as connexion:
        connexion.execute(text("CREATE TABLE enrollments (id INTEGER PRIMARY KEY)"))
        connexion.execute(text("CREATE TABLE students (id INTEGER PRIMARY KEY)"))
        connexion.execute(
            text(
                "CREATE TABLE scholarships (id INTEGER PRIMARY KEY,"
                " enrollment_id INTEGER NOT NULL, kind VARCHAR(20) NOT NULL)"
            )
        )
        for identifiant, inscription in bourses:
            connexion.execute(
                text("INSERT INTO scholarships VALUES (:i, :e, 'demi_bourse')"),
                {"i": identifiant, "e": inscription},
            )
    return moteur


def test_des_bourses_en_double_arretent_la_migration_sans_rien_ecrire() -> None:
    moteur = _base([(1, 7), (2, 7), (3, 8), (4, 9), (5, 9)])

    with moteur.begin() as connexion:
        contexte = MigrationContext.configure(connection=connexion)
        with Operations.context(contexte), pytest.raises(RuntimeError) as refus:
            _migration().upgrade()

    assert "7, 9" in str(refus.value)
    assert "rien n'a été modifié" in str(refus.value)
    colonnes = {c["name"] for c in inspect(moteur).get_columns("enrollments")}
    assert colonnes == {"id"}
    assert inspect(moteur).get_indexes("scholarships") == []


def test_une_base_sans_doublon_passe_la_verification() -> None:
    moteur = _base([(1, 7), (2, 8)])

    with moteur.begin() as connexion:
        contexte = MigrationContext.configure(connection=connexion)
        with Operations.context(contexte):
            _migration()._refuse_duplicate_scholarships()
