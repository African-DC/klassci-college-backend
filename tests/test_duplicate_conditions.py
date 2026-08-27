"""Le filet de la requête de doublons : elle ne doit JAMAIS rendre tout le fichier.

Ce fichier existe parce que la sentinelle qu'il garde n'avait aucun siège
testable. On pouvait la retirer, la suite entière restait verte, et la requête
de recherche se mettait à rendre le fichier élèves complet — 200 fiches
arbitraires présentées comme des doublons possibles, sur un écran où la
secrétaire décide de créer ou non un dossier.

Un garde que rien ne teste est un garde que la prochaine refonte enlève.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import or_, select
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import SADeprecationWarning
from sqlalchemy.sql.elements import False_

from app.models.user import Student
from app.services.duplicates.detection import _candidate_conditions


def _sql(requete: object) -> str:
    return str(
        requete.compile(  # type: ignore[attr-defined]
            dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


@pytest.mark.parametrize(
    ("nom", "prenom", "matricule", "naissance"),
    [
        (None, None, None, None),
        ("", "", "", None),
        ("   ", "   ", "   ", None),
        ("!!", "??", None, None),
    ],
)
def test_une_saisie_sans_critere_ne_desigme_personne(
    nom: str | None, prenom: str | None, matricule: str | None, naissance: date | None
) -> None:
    """Rien de exploitable en entrée doit vouloir dire « personne », pas « tout le monde ».

    Une liste de conditions vide fait disparaître la clause WHERE : la requête
    rend alors la table entière. C'est le comportement de `or_()` en SQLAlchemy,
    pas une hypothèse — le test suivant le montre.
    """
    conditions = _candidate_conditions(nom, prenom, matricule, naissance)
    assert conditions, "la liste ne doit jamais être vide"
    assert "0 = 1" in _sql(select(Student.id).where(or_(*conditions)))


def test_sans_sentinelle_la_requete_rendrait_tout_le_fichier() -> None:
    """Ce que coûte l'oubli, montré plutôt qu'affirmé en commentaire.

    Sans ce test, la phrase « un or_() vide supprime la clause WHERE » n'est
    qu'une croyance sur une bibliothèque tierce, qu'une montée de version peut
    démentir en silence.
    """
    # L'avertissement de depreciation est attendu : c'est precisement l'appel
    # que la sentinelle existe pour ne jamais produire.
    with pytest.warns(SADeprecationWarning):
        sans_filet = _sql(select(Student.id).where(or_()))
    assert "WHERE" not in sans_filet, (
        "si SQLAlchemy cesse de supprimer la clause, la sentinelle change de rôle "
        "et son commentaire doit être réécrit"
    )


def test_une_saisie_reelle_ne_porte_pas_la_sentinelle() -> None:
    """La sentinelle ne doit apparaître que seule.

    L'assertion porte sur la LISTE rendue, pas sur le SQL compilé. Une version
    antérieure comparait la chaîne compilée et ne pouvait pas échouer :
    SQLAlchemy 2.0 replie la constante hors d'un `or_()` peuplé, donc la
    sentinelle ajoutée en tête disparaissait du SQL avant l'assertion. Le test
    mesurait la bibliothèque, pas le code.

    En SQL brut, la sentinelle en tête coûte cher — SQLite abandonne alors
    MULTI-INDEX OR. Ne pas l'ajouter est ce qui rend l'index indépendant du
    repliage de SQLAlchemy.
    """
    conditions = _candidate_conditions("YAO", "Aya", None, None)
    assert len(conditions) > 1, "cette saisie doit produire de vrais critères"
    constantes = [c for c in conditions if isinstance(c, False_)]
    assert not constantes, "aucune sentinelle ne doit accompagner de vrais critères"
