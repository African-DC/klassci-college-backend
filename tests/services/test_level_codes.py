"""Le nom libre d'un niveau devient un code national, ou rien."""

import pytest

from app.models.enrollment import PreviousLevel
from app.services.level_codes import national_level_code


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("CM2", PreviousLevel.CM2),
        ("6ème", PreviousLevel.SIXIEME),
        ("6eme", PreviousLevel.SIXIEME),
        ("6e", PreviousLevel.SIXIEME),
        ("Sixième", PreviousLevel.SIXIEME),
        ("6", PreviousLevel.SIXIEME),
        ("5ème", PreviousLevel.CINQUIEME),
        ("Cinquième", PreviousLevel.CINQUIEME),
        ("4eme", PreviousLevel.QUATRIEME),
        ("Quatrième", PreviousLevel.QUATRIEME),
        ("3ème", PreviousLevel.TROISIEME),
        ("Troisième", PreviousLevel.TROISIEME),
        ("2nde C", PreviousLevel.SECONDE),
        ("2de A", PreviousLevel.SECONDE),
        ("Seconde", PreviousLevel.SECONDE),
        ("1ère D", PreviousLevel.PREMIERE),
        ("1re A", PreviousLevel.PREMIERE),
        ("Première C", PreviousLevel.PREMIERE),
        ("Terminale D", PreviousLevel.TERMINALE),
        ("Tle A", PreviousLevel.TERMINALE),
        ("  TERMINALE  ", PreviousLevel.TERMINALE),
    ],
)
def test_un_nom_connu_donne_son_code(name: str, expected: PreviousLevel) -> None:
    assert national_level_code(name) is expected


@pytest.mark.parametrize("name", ["", None, "Maternelle", "BTS 1", "Classe passerelle"])
def test_un_nom_inconnu_ne_donne_rien(name: str | None) -> None:
    assert national_level_code(name) is None
