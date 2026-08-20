"""Affecté / non affecté — la ligne la plus structurante d'une grille ivoirienne."""

from app.models.enrollment import AssignmentStatus
from app.models.fee import FeeAssignmentScope, FeeVariant
from app.services.enrollment_service import fee_variant_assignment_predicate


def _bound_scope(predicate: object) -> str | None:
    """Valeur reellement liee au parametre SQL.

    `str()` d'une clause n'imprime que `:assignment_scope_1` : deux portees
    differentes produisent donc la meme chaine, et comparer les chaines ne
    prouverait rien.
    """
    compiled = predicate.compile(compile_kwargs={"literal_binds": False})  # type: ignore[attr-defined]
    values = [v for v in compiled.params.values() if v is not None]
    return str(getattr(values[0], "value", values[0])) if values else None


def _sql(predicate: object) -> str:
    return str(predicate).replace("\n", " ")


def test_le_reaffecte_est_subventionne_comme_un_affecte() -> None:
    """L'État le prend en charge : lui facturer le tarif plein serait faux."""
    assert AssignmentStatus.AFFECTE.is_subsidised
    assert AssignmentStatus.REAFFECTE.is_subsidised
    assert not AssignmentStatus.NON_AFFECTE.is_subsidised


def test_le_tarif_ne_connait_que_deux_cas() -> None:
    """Une troisième colonne « réaffecté » resterait vide en doublant la saisie."""
    assert {s.value for s in FeeAssignmentScope} == {"affecte", "non_affecte"}


def test_une_inscription_sans_statut_ne_recoit_que_les_tarifs_communs() -> None:
    """Lui donner le tarif affecté ou le tarif non affecté reviendrait à
    choisir pour l'école entre deux montants, et la famille le découvrirait
    sur sa facture."""
    sql = _sql(fee_variant_assignment_predicate(None))
    assert "IS NULL" in sql
    assert "OR" not in sql, "aucun tarif cible ne doit s'appliquer par defaut"


def test_un_affecte_recoit_les_tarifs_communs_et_les_siens() -> None:
    sql = _sql(fee_variant_assignment_predicate(AssignmentStatus.AFFECTE))
    assert "IS NULL" in sql, "les grilles deja configurees continuent de s'appliquer"
    assert "OR" in sql


def test_le_reaffecte_prend_le_meme_filtre_que_l_affecte() -> None:
    assert _bound_scope(fee_variant_assignment_predicate(AssignmentStatus.REAFFECTE)) == (
        _bound_scope(fee_variant_assignment_predicate(AssignmentStatus.AFFECTE))
    )


def test_un_non_affecte_ne_prend_pas_le_filtre_de_l_affecte() -> None:
    assert _bound_scope(fee_variant_assignment_predicate(AssignmentStatus.NON_AFFECTE)) == (
        FeeAssignmentScope.NON_AFFECTE.value
    )
    assert _bound_scope(fee_variant_assignment_predicate(AssignmentStatus.AFFECTE)) == (
        FeeAssignmentScope.AFFECTE.value
    )


def test_la_portee_entre_dans_la_cle_d_unicite() -> None:
    """Sans elle, l'école ne pourrait pas définir un tarif affecté ET un tarif
    non affecté pour le même niveau — c'est pourtant tout l'objet."""
    constraint = next(
        c
        for c in FeeVariant.__table__.constraints
        if getattr(c, "name", "") == "uq_fee_variant_category_level_series_year"
    )
    assert "assignment_scope" in {c.name for c in constraint.columns}


def test_le_predicat_accepte_la_valeur_brute_de_la_base() -> None:
    """SQLAlchemy peut renvoyer la chaine plutot que le membre d'enum."""
    assert _bound_scope(fee_variant_assignment_predicate("affecte")) == (
        _bound_scope(fee_variant_assignment_predicate(AssignmentStatus.AFFECTE))
    )
