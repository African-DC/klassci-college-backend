"""La 0079 s'arrête en NOMMANT, plutôt qu'en renvoyant un numéro d'erreur MySQL.

La CI joue `upgrade head` sur une base vide : la détection de doublons y trouve
zéro ligne, et c'est le seul morceau de cette migration qui contienne une
décision. Or cette décision est la seule chose qui distingue un déploiement
qu'on sait reprendre d'un déploiement qui s'arrête sur « Duplicate entry
'412-38' for key 'uq_payment_allocation' » — une chaîne qui ne désigne rien
pour la personne qui lit la sortie, et dont elle ne tire aucun geste.

La pose de la contrainte elle-même n'est pas éprouvée ici : SQLite ne sait pas
ajouter une contrainte à une table existante, et le rendu MySQL hors ligne
n'exécuterait pas la détection. C'est la CI, qui joue la révision sur MySQL,
qui répond de la pose.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

_SCHEMA = (
    "CREATE TABLE payment_allocations ("
    " id INTEGER PRIMARY KEY, payment_id INTEGER NOT NULL,"
    " enrollment_fee_id INTEGER NOT NULL, amount NUMERIC(15, 2) NOT NULL)"
)


def _charger_migration() -> ModuleType:
    """Importe la révision par son chemin : son nom de fichier commence par un chiffre."""
    chemin = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260904_0079_payment_allocation_uniqueness.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0079", chemin)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base(lignes: list[tuple[int, int, int, str]]):
    """Une table d'allocations sans la contrainte — la forme d'avant la 0079."""
    moteur = create_engine("sqlite://")
    with moteur.begin() as connexion:
        connexion.execute(text(_SCHEMA))
        for identifiant, versement, frais, montant in lignes:
            connexion.execute(
                text(
                    "INSERT INTO payment_allocations "
                    "(id, payment_id, enrollment_fee_id, amount) "
                    "VALUES (:i, :p, :f, :m)"
                ),
                {"i": identifiant, "p": versement, "f": frais, "m": montant},
            )
    return moteur


def test_une_base_saine_ne_presente_aucun_doublon() -> None:
    """Deux frais différents sur un même versement, c'est la répartition normale."""
    migration = _charger_migration()
    moteur = _base([(1, 412, 38, "2000"), (2, 412, 39, "3000"), (3, 413, 38, "1000")])

    with moteur.begin() as connexion:
        assert migration._doublons(connexion) == []


def test_deux_lignes_pour_un_meme_frais_sont_reperees_avec_leur_compte() -> None:
    """C'est le seul cas que la contrainte refuse, et donc le seul à repérer."""
    migration = _charger_migration()
    moteur = _base([(1, 412, 38, "2000"), (2, 412, 38, "3000"), (3, 413, 39, "1000")])

    with moteur.begin() as connexion:
        assert migration._doublons(connexion) == [(412, 38, 2)]


def test_la_migration_s_arrete_en_nommant_les_versements_concernes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le message doit porter de quoi agir : le versement, le frais, et la suite.

    Un arrêt qui ne nomme rien renvoie la personne au dump de la base pendant
    sa fenêtre de déploiement. Celui-ci lui donne l'identifiant à ouvrir et la
    commande qui listera le reste.

    `_has_index` interroge `information_schema`, que SQLite n'a pas ; le cas
    sous test est justement celui où l'index n'est pas encore posé.
    """
    migration = _charger_migration()
    monkeypatch.setattr(migration, "_has_index", lambda _bind: False)
    moteur = _base([(1, 412, 38, "2000"), (2, 412, 38, "3000")])

    with moteur.begin() as connexion:
        contexte = MigrationContext.configure(connection=connexion)
        with Operations.context(contexte), pytest.raises(RuntimeError) as leve:
            migration.upgrade()

    message = str(leve.value)
    assert "versement 412" in message
    assert "frais 38" in message
    assert "check_allocations" in message
    # Et surtout : la migration n'a rien touché. Fusionner deux lignes d'argent
    # reçu sans qu'un comptable ait tranché serait pire que de s'arrêter.
    with moteur.begin() as connexion:
        assert connexion.execute(text("SELECT COUNT(*) FROM payment_allocations")).scalar_one() == 2


def test_une_base_deja_contrainte_ne_relit_rien(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rejouable sans effet : l'index présent prouve à lui seul l'absence de doublon."""
    migration = _charger_migration()
    monkeypatch.setattr(migration, "_has_index", lambda _bind: True)
    moteur = _base([(1, 412, 38, "2000"), (2, 412, 38, "3000")])

    with moteur.begin() as connexion:
        contexte = MigrationContext.configure(connection=connexion)
        with Operations.context(contexte):
            migration.upgrade()
