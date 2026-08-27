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
from sqlalchemy import create_engine, text

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
