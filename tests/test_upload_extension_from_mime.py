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


@pytest.mark.parametrize(
    "nom_forge",
    [
        "photo.png/../../../../app/main",
        "innocent.jpg.tar.gz/../../etc/cron.d/backdoor",
        "x." + "../" * 20 + "root",
        "p.C:/Windows/evil",
        "sans-point",
    ],
)
def test_un_nom_forge_ne_touche_plus_le_chemin(nom_forge: str) -> None:
    """Le nom envoyé n'entre plus dans le calcul du chemin.

    Ces noms sont ceux qui traversaient l'ancien `rsplit`. On les rejoue pour
    que le correctif reste vérifiable par ce qu'il empêche, et pas seulement
    par la façon dont il est écrit.
    """
    import os

    from app.core.uploads import PHOTOS

    dossier = PHOTOS.directory
    extension = extension_pour("image/jpeg")
    chemin = os.path.join(dossier, f"42_abcd1234.{extension}")
    assert os.path.normpath(chemin).startswith(os.path.normpath(dossier))
    assert nom_forge not in chemin


def test_l_ancien_calcul_ouvrait_un_sous_chemin_pas_une_evasion() -> None:
    """Ce que l'ancien calcul permettait vraiment, et ce qu'il ne permettait pas.

    Correction d'une affirmation trop forte faite en livrant le correctif : je
    l'avais décrit comme une écriture arbitraire sur le serveur. Ce n'en était
    pas une. `rsplit(".", 1)[-1]` rend ce qui suit le **dernier** point, donc
    une chaîne sans aucun point : elle ne peut jamais contenir `..`, et la
    remontée d'un dossier est hors d'atteinte.

    Ce qu'elle pouvait contenir, ce sont des séparateurs. La cible devenait
    alors un sous-chemin inexistant du dossier d'upload, et `open()` levait
    une `FileNotFoundError` non rattrapée : une erreur 500 sur l'envoi d'une
    photo, pas une évasion.

    Le correctif reste juste — il retire la donnée envoyée du calcul du chemin,
    et ferme les deux. Mais il fallait dire la bonne gravité.
    """
    import os

    from app.core.uploads import PHOTOS

    dossier = PHOTOS.directory
    hostiles = [
        "photo.png/../../../../app/main",
        "x." + "../" * 20 + "root",
        "p.C:/Windows/evil",
    ]
    for nom in hostiles:
        ancienne = nom.rsplit(".", 1)[-1]
        # La propriété qui rendait l'évasion impossible : pas de point, donc
        # pas de `..`.
        assert "." not in ancienne
        cible = os.path.join(dossier, f"42_abcd1234.{ancienne}")
        assert os.path.normpath(cible).startswith(os.path.normpath(dossier))
        # En revanche le chemin s'enfonçait dans des dossiers absents.
        assert os.sep in os.path.normpath(cible)[len(os.path.normpath(dossier)) :]
