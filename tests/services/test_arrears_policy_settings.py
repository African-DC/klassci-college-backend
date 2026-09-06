"""Le réglage des dettes d'un exercice précédent, et son défaut qui ne fait rien.

Ce que ces tests gardent tient en une phrase : une école qui n'ouvre jamais cet
écran ne doit voir aucun changement. Pas de bandeau, pas de refus, et pas une
requête de plus — le garde sort avant d'avoir de quoi interroger la moindre
dette. C'est la forme du retour de `policy_in_force` qui le garantit, et c'est
elle qu'on vérifie ici, pas un commentaire.

Le reste couvre la trace : sans le journal d'audit, plus rien ne dit sous
quelle règle un dossier a été accepté, et il faudrait dater la règle sur chaque
inscription.
"""

from collections.abc import Iterator
from importlib import util as import_util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import Integer, MetaData, create_engine, select
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.models.academic import ArrearsPolicy, SchoolSettings
from app.schemas.arrears_policy import ArrearsPolicyUpdate
from app.services import arrears_policy as service

_MIGRATION = "20260906_0081_arrears_policy_settings.py"


def _cree_sur_sqlite(table: Any, engine: Any) -> None:
    """Crée la table sur SQLite, avec une clé primaire qu'il sait incrémenter.

    En production les identifiants sont des `BIGINT AUTO_INCREMENT` ; SQLite ne
    numérote automatiquement que les `INTEGER PRIMARY KEY`. On ne change que le
    type de la copie utilisée pour créer la table de test : le SQL exercé reste
    celui du service.
    """
    copie = table.to_metadata(MetaData())
    copie.c.id.type = Integer()
    copie.create(engine)


class _NoopTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _AsyncBridge:
    """Une `AsyncSession` de façade au-dessus d'une session synchrone.

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
        self._session.flush()

    def begin_nested(self) -> Any:
        return _NoopTransaction()


@pytest.fixture
def db() -> Iterator[tuple[_AsyncBridge, Session]]:
    """Un établissement sans aucune ligne de réglages — l'état d'un tenant neuf."""
    engine = create_engine("sqlite://")
    _cree_sur_sqlite(SchoolSettings.__table__, engine)
    _cree_sur_sqlite(AuditLog.__table__, engine)

    with Session(engine) as session:
        yield _AsyncBridge(session), session

    engine.dispose()


def _journal(session: Session) -> list[AuditLog]:
    return list(session.execute(select(AuditLog)).scalars().all())


def _migration() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / _MIGRATION
    spec = import_util.spec_from_file_location("migration_0081", path)
    assert spec is not None and spec.loader is not None
    module = import_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Le défaut est l'identité
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_une_ecole_qui_na_rien_regle_na_pas_de_politique(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """Aucune ligne de réglages : l'absence vaut `off`, comme la colonne."""
    bridge, session = db

    assert await service.policy_in_force(bridge) is None
    assert session.execute(select(SchoolSettings)).first() is None, (
        "le chemin de garde ne provisionne rien : il lit, il n'écrit jamais"
    )


@pytest.mark.asyncio
async def test_le_defaut_est_off_et_le_garde_sort_avant(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """`off` rend `None` — l'appelant n'a même pas de quoi interroger une dette.

    On compte les requêtes : la lecture du singleton est la seule. C'est la
    promesse faite à une école qui n'ouvre jamais cet écran, et elle se mesure.
    """
    bridge, _session = db
    etat = await service.get_settings(bridge)
    assert etat.arrears_policy is ArrearsPolicy.OFF
    assert etat.arrears_block_threshold_xof == 0

    avant = bridge.executions
    assert await service.policy_in_force(bridge) is None
    assert bridge.executions - avant == 1


# ---------------------------------------------------------------------------
# Ce que l'école active, elle-même
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_informer_ne_bloque_pas(db: tuple[_AsyncBridge, Session]) -> None:
    bridge, _session = db
    await service.update_settings(
        bridge,
        ArrearsPolicyUpdate(arrears_policy=ArrearsPolicy.INFORM, arrears_block_threshold_xof=0),
        updated_by=1,
    )

    politique = await service.policy_in_force(bridge)
    assert politique is not None
    assert politique.policy is ArrearsPolicy.INFORM
    assert politique.blocks is False


@pytest.mark.asyncio
async def test_bloquer_porte_son_seuil(db: tuple[_AsyncBridge, Session]) -> None:
    bridge, _session = db
    await service.update_settings(
        bridge,
        ArrearsPolicyUpdate(arrears_policy=ArrearsPolicy.BLOCK, arrears_block_threshold_xof=50_000),
        updated_by=7,
    )

    politique = await service.policy_in_force(bridge)
    assert politique is not None
    assert politique.blocks is True
    assert politique.block_threshold_xof == 50_000


@pytest.mark.asyncio
async def test_le_seuil_survit_a_un_passage_par_off(db: tuple[_AsyncBridge, Session]) -> None:
    """Désactiver puis réactiver ne doit pas reprendre à la direction son chiffre."""
    bridge, _session = db
    for politique in (ArrearsPolicy.BLOCK, ArrearsPolicy.OFF):
        await service.update_settings(
            bridge,
            ArrearsPolicyUpdate(arrears_policy=politique, arrears_block_threshold_xof=25_000),
            updated_by=1,
        )

    assert await service.policy_in_force(bridge) is None, "off ne bloque rien"
    etat = await service.get_settings(bridge)
    assert etat.arrears_block_threshold_xof == 25_000


def test_un_seuil_negatif_na_pas_de_sens() -> None:
    """Un montant en francs CFA n'est jamais négatif : refusé avant la base."""
    with pytest.raises(ValidationError):
        ArrearsPolicyUpdate(arrears_policy=ArrearsPolicy.BLOCK, arrears_block_threshold_xof=-1)


def test_les_deux_champs_sont_obligatoires() -> None:
    """Un corps incomplet sort en 422, jamais en écriture à moitié silencieuse.

    C'est le piège de `update_school_info`, qui fait `exclude_none=True` : un
    champ envoyé à `null` y est jeté sans un mot. `update_fee_variant` a dû
    passer à `exclude_unset` pour la même raison. Ici, les deux colonnes étant
    NOT NULL, la question ne se pose pas : on exige la politique entière.
    """
    with pytest.raises(ValidationError):
        ArrearsPolicyUpdate(arrears_policy=ArrearsPolicy.BLOCK)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# La trace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_le_changement_de_regle_est_journalise(db: tuple[_AsyncBridge, Session]) -> None:
    """Sans cette trace, plus rien ne dit sous quelle règle un dossier est passé.

    C'est en la croisant avec le journal des inscriptions qu'on le sait, et
    c'est ce qui a permis d'écarter une colonne datée sur `enrollments`.
    """
    bridge, session = db
    await service.update_settings(
        bridge,
        ArrearsPolicyUpdate(
            arrears_policy=ArrearsPolicy.BLOCK, arrears_block_threshold_xof=100_000
        ),
        updated_by=42,
    )

    entrees = _journal(session)
    assert len(entrees) == 1
    trace = entrees[0]
    assert trace.entity_type == "school_settings"
    assert trace.user_id == 42
    assert trace.old_values == {"arrears_policy": "off", "arrears_block_threshold_xof": 0}
    assert trace.new_values == {
        "arrears_policy": "block",
        "arrears_block_threshold_xof": 100_000,
    }


@pytest.mark.asyncio
async def test_un_reglage_reenonce_a_lidentique_najoute_rien(
    db: tuple[_AsyncBridge, Session],
) -> None:
    """Le journal enregistre des transitions ; un PUT sans changement n'en est pas une."""
    bridge, session = db
    inchange = ArrearsPolicyUpdate(arrears_policy=ArrearsPolicy.OFF, arrears_block_threshold_xof=0)

    await service.update_settings(bridge, inchange, updated_by=1)

    assert _journal(session) == []


# ---------------------------------------------------------------------------
# Le code et la migration disent la même chose
# ---------------------------------------------------------------------------


def test_la_migration_pose_les_memes_valeurs_que_le_modele() -> None:
    """Une quatrième valeur ajoutée d'un seul côté serait refusée par la base."""
    assert _migration()._POLITIQUES == tuple(p.value for p in ArrearsPolicy)


def test_le_defaut_de_la_base_est_off() -> None:
    """Le défaut vit dans la colonne, pas seulement dans le code applicatif.

    Une école déjà en service reçoit ses deux colonnes par `ALTER TABLE` : si le
    `server_default` disait autre chose, la politique s'activerait toute seule
    au redémarrage, sans que personne ne l'ait décidée.
    """
    colonnes = SchoolSettings.__table__.c
    assert colonnes.arrears_policy.server_default.arg == ArrearsPolicy.OFF.value
    assert colonnes.arrears_block_threshold_xof.server_default.arg == "0"
