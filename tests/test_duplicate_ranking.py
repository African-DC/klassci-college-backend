"""L'ordre dans lequel l'écran présente les correspondances.

La secrétaire lit la première ligne. Ce qu'on y met décide si elle réinscrit
l'élève qu'elle a devant elle ou celui d'à côté.

Deux axes, dans cet ordre : une certitude — le matricule identique, qui désigne
une personne — passe avant une ressemblance, aussi forte soit-elle ; à égalité
de nature, le score range du plus sûr au moins sûr.

Le second axe était gardé ; le premier ne l'était pas. Un score absent est
projeté sur 1.0, déjà le maximum, si bien que la nature ne départage que contre
une ressemblance de EXACTEMENT 1.0. Cette égalité parfaite s'obtient au guichet :
mêmes nom, prénom et date de naissance qu'un frère ou une soeur, plus un
matricule recopié du papier de la famille. Là, sans le premier axe, l'écran met
l'homonyme devant la personne.
"""

from datetime import date

from app.schemas.duplicates import MatchResponse
from app.services.duplicates.detection import _by_certainty_then_score


def _correspondance(matricule: str, raison: str, score: float | None) -> MatchResponse:
    return MatchResponse(
        student_id=1,
        last_name="KOUASSI",
        first_name="Aya",
        enrollment_number=matricule,
        birth_date=date(2011, 1, 1),
        reason=raison,  # type: ignore[arg-type]
        score=score,
        partial_identity=False,
        current_year_enrollment=None,
    )


def test_le_matricule_identique_passe_avant_une_ressemblance_parfaite() -> None:
    """Le cas que le second axe seul ne sait pas trancher.

    Une ressemblance à 1.0 et un matricule identique arrivent tous deux au
    sommet de l'axe du score : seule la nature de la correspondance les
    départage. Sans elle, l'homonyme parfait passe devant la personne.
    """
    ressemblance = _correspondance("ECER0002", "similarity", 1.0)
    certitude = _correspondance("ECER0001", "enrollment_number", None)

    ordonne = sorted([ressemblance, certitude], key=_by_certainty_then_score)

    assert ordonne[0].reason == "enrollment_number", (
        "le matricule identique désigne une personne ; la ressemblance n'en désigne qu'une possible"
    )


def test_a_nature_egale_le_plus_sur_passe_devant() -> None:
    """Le second axe, entre deux ressemblances."""
    faible = _correspondance("ECER0003", "similarity", 0.74)
    forte = _correspondance("ECER0004", "similarity", 0.95)

    ordonne = sorted([faible, forte], key=_by_certainty_then_score)

    assert [c.score for c in ordonne] == [0.95, 0.74]
