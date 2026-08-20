"""L'ordre des gestes quand une fiche élève est détruite.

Ce n'est pas un détail de style : figer le nom après avoir supprimé
l'inscription revient à ne rien figer du tout, et détacher les versements
après avoir tenté de supprimer l'inscription échoue sur la clé étrangère.
L'ordre EST la fonctionnalité.

Ces tests ne vérifient donc pas ce que la base ferait — ils vérifient la
suite d'ordres SQL émise, contre une session factice.
"""

from types import SimpleNamespace

from app.repositories.student_purge_repository import (
    purge_student_keeping_payments,
    student_display_name,
)


class _ScalarResult:
    def __init__(self, values: list, *, scalar: int = 0, rowcount: int = 0) -> None:
        self._values = values
        self._scalar = scalar
        self.rowcount = rowcount

    def scalars(self) -> list:
        return self._values

    def scalar(self) -> int:
        return self._scalar


class _PurgeDb:
    """Session factice qui répond juste assez pour dérouler la purge."""

    def __init__(self) -> None:
        self.ordres: list[str] = []

    async def execute(self, statement: object, *_a: object, **_k: object) -> _ScalarResult:
        rendu = str(statement).lower()
        self.ordres.append(rendu)
        if "count" in rendu:
            return _ScalarResult([], scalar=3)
        if rendu.startswith("select") and "from enrollments" in rendu:
            return _ScalarResult([7])
        if rendu.startswith("select") and "from enrollment_fees" in rendu:
            return _ScalarResult([11, 12])
        return _ScalarResult([], rowcount=2)

    async def flush(self) -> None:
        return None

    def expunge(self, _obj: object) -> None:
        return None


def _index_of(ordres: list[str], fragment: str) -> int:
    for i, ordre in enumerate(ordres):
        if fragment in ordre:
            return i
    raise AssertionError(f"aucun ordre SQL ne contient « {fragment} » : {ordres}")


def _eleve() -> SimpleNamespace:
    return SimpleNamespace(id=14, first_name="Aminata", last_name="Traoré", enrollment_number="M1")


async def test_l_identite_est_figee_avant_toute_destruction() -> None:
    """Une fois la fiche partie, on ne peut plus relire le nom qu'on aurait dû
    recopier."""
    db = _PurgeDb()
    await purge_student_keeping_payments(db, _eleve())

    fige = _index_of(db.ordres, "student_name_snapshot")
    detache = _index_of(db.ordres, "set enrollment_id=:enrollment_id")
    supprime = _index_of(db.ordres, "delete from enrollments")
    assert fige < detache < supprime


async def test_la_purge_ne_supprime_jamais_un_versement() -> None:
    """La règle qui commande tout : l'argent encaissé ne s'efface pas."""
    db = _PurgeDb()
    await purge_student_keeping_payments(db, _eleve())
    assert not any("delete from payments" in ordre for ordre in db.ordres)


async def test_les_repartitions_partent_avec_les_frais() -> None:
    """Elles désignent une dette qui n'existe plus. Le versement, lui, garde
    son montant total — la seule somme qui compte pour la caisse."""
    db = _PurgeDb()
    await purge_student_keeping_payments(db, _eleve())
    reparties = _index_of(db.ordres, "delete from payment_allocations")
    frais = _index_of(db.ordres, "delete from enrollment_fees")
    assert reparties < frais


async def test_la_purge_rend_l_inventaire_de_ce_qu_elle_emporte() -> None:
    """« Supprimé » sans dire quoi ne vaut guère mieux que pas de trace."""
    db = _PurgeDb()
    inventaire = await purge_student_keeping_payments(db, _eleve())
    phrases = [d.phrase() for d in inventaire]
    assert "1 inscription" in phrases
    assert any("versement" in phrase for phrase in phrases), phrases


def test_un_eleve_sans_nom_garde_quand_meme_une_identite_figee() -> None:
    """Le nom recopié est tout ce qui restera : il ne peut pas être vide."""
    assert student_display_name(SimpleNamespace(id=9, first_name="", last_name="")) == "Élève 9"
