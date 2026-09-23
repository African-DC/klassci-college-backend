"""Tests de `frozen` — ce qui entre dans la colonne « Avant » du journal.

Ces tests appellent la fonction et regardent ce qu'elle produit. Ils ne
lisent pas son code source : un test qui vérifie la présence d'une ligne fige
l'écriture au lieu de vérifier le comportement.
"""

import enum
from datetime import date, datetime, time
from decimal import Decimal

import pytest

from app.core.audit_values import frozen, json_safe


class _Genre(str, enum.Enum):
    F = "F"
    M = "M"


class _Fiche:
    """Un objet au profil d'un modèle ORM : montants, dates, énumérations."""

    def __init__(self) -> None:
        self.name = "6e B"
        self.amount = Decimal("50000.00")
        self.birth_date = date(2012, 4, 7)
        self.start_time = time(8, 0)
        self.created_at = datetime(2026, 9, 22, 11, 4)
        self.genre = _Genre.F
        self.is_current = True
        self.description = None


def test_frozen_rend_des_valeurs_serialisables_en_json() -> None:
    """Les types qui feraient tomber l'insertion JSON sont convertis.

    `Decimal`, `date` et énumération lèvent un TypeError à l'écriture, et
    `audit_log` propage ce TypeError : la requête métier finirait en 500.
    """
    import json

    snapshot = frozen(
        _Fiche(),
        "name",
        "amount",
        "birth_date",
        "start_time",
        "created_at",
        "genre",
        "is_current",
        "description",
    )

    assert snapshot == {
        "name": "6e B",
        # Chaîne, pas float : un montant en francs ne transite pas par un
        # binaire flottant entre la caisse et le journal.
        "amount": "50000.00",
        "birth_date": "2012-04-07",
        "start_time": "08:00:00",
        "created_at": "2026-09-22T11:04:00",
        "genre": "F",
        "is_current": True,
        "description": None,
    }
    json.dumps(snapshot)


def test_frozen_ne_prend_que_les_champs_nommes() -> None:
    """Rien n'est capturé qui n'ait été demandé.

    C'est la garantie qui tient les secrets hors du journal : un mot de passe
    ou une clé API n'entre en base que si quelqu'un a tapé son nom ici.
    """

    class _Compte:
        email = "sophie.yao@klassci.com"
        hashed_password = "$2b$12$secret"

    assert frozen(_Compte(), "email") == {"email": "sophie.yao@klassci.com"}


def test_frozen_signale_une_cle_inexistante() -> None:
    """Une clé de payload qui n'est pas un attribut du modèle est un bug.

    `update_room` en donne l'exemple : `class_id` arrive dans le payload et
    vit sur `Class`, pas sur `Room`. Mieux vaut tomber en test que journaliser
    à moitié en silence.
    """
    with pytest.raises(AttributeError):
        frozen(_Fiche(), "class_id")


def test_frozen_refuse_une_relation() -> None:
    """Une relation ORM ne se compare pas : on fige l'identifiant, pas l'objet."""

    class _Lie:
        _sa_instance_state = object()

    class _Parent:
        enfant = _Lie()

    with pytest.raises(TypeError, match="relation"):
        frozen(_Parent(), "enfant")


def test_json_safe_descend_dans_les_listes_et_les_dictionnaires() -> None:
    """Un échéancier supprimé est une liste de lignes, pas une valeur plate."""
    assert json_safe([{"amount": Decimal("1000"), "due_date": date(2026, 10, 5)}]) == [
        {"amount": "1000", "due_date": "2026-10-05"}
    ]


def test_frozen_changed_refuse_une_cle_qui_n_est_pas_une_colonne() -> None:
    """Un payload qui porte autre chose qu'une colonne est un bug de service.

    `update_room` reçoit `class_id`, qui vit sur `Class` et non sur `Room` :
    le service le retire lui-même. Un service qui l'oublierait doit le voir en
    test, pas journaliser la moitié des champs en silence.
    """
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    from app.core.audit_values import frozen_changed

    class _Base(DeclarativeBase):
        pass

    class _Salle(_Base):
        __tablename__ = "salles_de_test"
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str] = mapped_column()

    salle = _Salle(id=1, name="Salle 6e B")

    assert frozen_changed(salle, {"name": "Salle 6e A"}) == {"name": "Salle 6e B"}

    with pytest.raises(AttributeError, match="class_id"):
        frozen_changed(salle, {"name": "x", "class_id": 7})


def test_subject_of_nomme_sans_toucher_la_base() -> None:
    """Le nom se lit sur l'objet en main, jamais par une requête."""
    from types import SimpleNamespace

    from app.core.audit_values import subject_of

    eleve = SimpleNamespace(
        first_name="Aminata", last_name="Traoré", enrollment_number="CI-2026-0012"
    )
    assert subject_of(eleve) == "Aminata Traoré · CI-2026-0012"

    sans_matricule = SimpleNamespace(first_name="Sophie", last_name="Yao")
    assert subject_of(sans_matricule) == "Sophie Yao"

    classe = SimpleNamespace(name="6e B")
    assert subject_of(classe) == "6e B"

    evaluation = SimpleNamespace(title="Devoir de mathématiques")
    assert subject_of(evaluation) == "Devoir de mathématiques"

    # Rien qui ressemble à un nom : l'écran affichera le type et le numéro,
    # et le dira comme tel plutôt que d'inventer un libellé.
    assert subject_of(SimpleNamespace(quantity=3)) is None
