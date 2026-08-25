"""
Le nom du fichier envoyé ne doit jamais décider d'un chemin sur le disque.

L'ancienne extraction, `nom.rsplit(".", 1)[-1]`, rendait tout ce qui suit le
dernier point — séparateurs compris. Un fichier nommé
`photo.png/../../../../app/main` produisait l'extension
`png/../../../../app/main`, que `os.path.join` suivait hors du dossier
d'upload : un compte autorisé à changer une photo pouvait écrire n'importe où
sur le serveur.

Ces tests appellent la vraie fonction plutôt que de relire le code : c'est
l'extension rendue qui compte, pas la forme de l'expression qui la calcule.
"""

import pytest
from fastapi import HTTPException

from app.utils.photo_upload import extension_pour


@pytest.mark.parametrize(
    ("type_mime", "attendu"),
    [("image/jpeg", "jpg"), ("image/png", "png"), ("image/webp", "webp")],
)
def test_extension_vient_du_type(type_mime: str, attendu: str) -> None:
    assert extension_pour(type_mime) == attendu


@pytest.mark.parametrize("type_mime", [None, "", "text/html", "application/x-python"])
def test_un_type_non_image_est_refuse(type_mime: str | None) -> None:
    with pytest.raises(HTTPException) as erreur:
        extension_pour(type_mime)
    assert erreur.value.status_code == 400


def test_aucune_extension_ne_contient_de_separateur() -> None:
    # La propriété qui ferme la traversée : quoi qu'il arrive en amont, ce que
    # la fonction rend ne peut pas sortir du dossier.
    from app.utils.photo_upload import EXTENSION_PAR_TYPE

    for extension in EXTENSION_PAR_TYPE.values():
        assert "/" not in extension
        assert "\\" not in extension
        assert ".." not in extension
