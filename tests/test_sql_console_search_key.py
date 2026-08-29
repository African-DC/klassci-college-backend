"""La console SQL doit prévenir quand une écriture rend un élève introuvable.

`students.last_name_key` et `first_name_key` portent la forme comparable du nom,
celle qu'interroge la détection de doublon. Le modèle les maintient à chaque
écriture ORM — mais cette console écrit en SQL brut, hors du modèle. C'est le
seul chemin du dépôt qui contourne ce validateur.

Un `UPDATE students SET last_name = ...` laisse donc la clé sur l'ancienne
orthographe. L'élève devient invisible à la détection : on peut le recréer en
double, avec une seconde ardoise que personne ne rapprochera de la première.

L'outil est risqué par construction et réservé au super-admin ; on ne l'interdit
pas, on prévient. L'avertissement paraît en mode `dry_run`, avant exécution.
"""

import pytest

from app.services.db_query_service import analyse_sql

CODE = "STUDENT_NAME_WITHOUT_SEARCH_KEY"


def _codes(sql: str) -> list[str]:
    return [avertissement["code"] for avertissement in analyse_sql(sql)]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE students SET last_name = 'NGUESSAN' WHERE id = 3",
        "UPDATE students SET first_name = 'Aya' WHERE id = 3",
        "UPDATE `students` SET last_name = 'X' WHERE id = 3",
        "INSERT INTO students (last_name, first_name) VALUES ('X', 'Y')",
        # Une seule des deux clés est posée : l'autre reste périmée.
        "UPDATE students SET last_name='X', last_name_key='x', first_name='Y' WHERE id=3",
    ],
)
def test_une_ecriture_de_nom_sans_sa_cle_est_signalee(sql: str) -> None:
    """Chaque forme d'écriture qui laisse une clé périmée doit être signalée."""
    assert CODE in _codes(sql), f"aucun avertissement sur : {sql}"


@pytest.mark.parametrize(
    "sql",
    [
        # Les deux colonnes écrites ensemble : rien à signaler.
        "UPDATE students SET last_name = 'NGUESSAN', last_name_key = 'nguessan' WHERE id = 3",
        (
            "INSERT INTO students (last_name, last_name_key, first_name, first_name_key) "
            "VALUES ('X', 'x', 'Y', 'y')"
        ),
        # Une écriture qui ne touche pas au nom.
        "UPDATE students SET city = 'Bouake' WHERE id = 3",
        # Une autre table.
        "UPDATE payments SET amount = 100 WHERE id = 1",
        # Une lecture ne périme rien.
        "SELECT last_name FROM students WHERE id = 3",
    ],
)
def test_une_ecriture_saine_ne_derange_personne(sql: str) -> None:
    """Un avertissement qui crie sur tout n'est plus lu par personne.

    C'est la moitié qui manque au test précédent : sans elle, un avertissement
    déclenché sur chaque requête passerait aussi.
    """
    assert CODE not in _codes(sql), f"avertissement injustifié sur : {sql}"


def test_le_message_dit_la_colonne_et_le_remede() -> None:
    """Devant une console SQL, un code d'erreur seul ne sert à rien.

    Le message doit nommer la colonne fautive et dire quoi écrire à la place,
    sinon le super-admin relance la même requête en ajoutant au hasard.
    """
    (avertissement,) = [
        a
        for a in analyse_sql("UPDATE students SET last_name = 'X' WHERE id = 3")
        if a["code"] == CODE
    ]
    assert "last_name_key" in avertissement["message"]
    assert "compact()" in avertissement["message"]
    assert avertissement["severity"] == "danger"
