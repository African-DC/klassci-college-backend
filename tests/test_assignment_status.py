"""Affecté / non affecté — la ligne la plus structurante d'une grille ivoirienne."""

from app.models.enrollment import AssignmentStatus
from app.models.fee import FeeAssignmentScope, FeeVariant
from app.services.enrollment_fees import applicable_scope_keys, applicable_series_keys


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
    assert applicable_scope_keys(None) == ("",)


def test_un_affecte_est_candidat_aux_tarifs_communs_et_aux_siens() -> None:
    """Les deux sont candidats ; c'est la résolution qui tranche ensuite pour
    n'en retenir qu'un, le plus spécifique."""
    assert set(applicable_scope_keys(AssignmentStatus.AFFECTE)) == {
        "",
        FeeAssignmentScope.AFFECTE.value,
    }


def test_le_reaffecte_prend_le_meme_filtre_que_l_affecte() -> None:
    assert applicable_scope_keys(AssignmentStatus.REAFFECTE) == applicable_scope_keys(
        AssignmentStatus.AFFECTE
    )


def test_un_non_affecte_n_est_jamais_candidat_au_tarif_de_l_affecte() -> None:
    assert FeeAssignmentScope.AFFECTE.value not in applicable_scope_keys(
        AssignmentStatus.NON_AFFECTE
    )
    assert FeeAssignmentScope.NON_AFFECTE.value not in applicable_scope_keys(
        AssignmentStatus.AFFECTE
    )


def test_le_filtre_accepte_la_valeur_brute_de_la_base() -> None:
    """SQLAlchemy peut renvoyer la chaine plutot que le membre d'enum."""
    assert applicable_scope_keys("affecte") == applicable_scope_keys(AssignmentStatus.AFFECTE)


def test_une_classe_sans_serie_ne_recoit_que_les_tarifs_sans_serie() -> None:
    """Au collège la série est toujours vide : lui laisser voir les tarifs de
    série A2 reviendrait à facturer un tarif de lycée à un élève de 6e."""
    assert applicable_series_keys(None) == (0,)
    assert set(applicable_series_keys(7)) == {0, 7}


def test_la_portee_entre_dans_la_cle_d_unicite() -> None:
    """Sans elle, l'école ne pourrait pas définir un tarif affecté ET un tarif
    non affecté pour le même niveau — c'est pourtant tout l'objet.

    La clé porte sur les colonnes générées : `NULL` n'étant jamais égal à
    `NULL`, une contrainte posée directement sur les colonnes nullables ne se
    déclencherait jamais.
    """
    constraint = next(
        c
        for c in FeeVariant.__table__.constraints
        if getattr(c, "name", "") == "uq_fee_variant_dimensions"
    )
    assert {c.name for c in constraint.columns} == {
        "fee_category_id",
        "academic_year_id",
        "level_key",
        "series_key",
        "scope_key",
        # Le profil d'inscription est entré dans la clé pour la même raison
        # que la portée : sans lui, un tarif « nouveau » et la grille générale
        # ne pourraient pas coexister sur la même catégorie.
        "profile_key",
    }


def test_les_colonnes_de_cle_neutralisent_les_valeurs_vides() -> None:
    """C'est ce qui laissait créer des tarifs en double sur tous les niveaux
    de collège, où la série est toujours vide."""
    for name, expression in (
        ("level_key", "COALESCE(level_id, 0)"),
        ("series_key", "COALESCE(series_id, 0)"),
        ("scope_key", "COALESCE(assignment_scope, '')"),
        ("profile_key", "COALESCE(enrollment_profile, '')"),
    ):
        column = FeeVariant.__table__.columns[name]
        assert column.computed is not None, f"{name} doit etre calculee par la base"
        assert str(column.computed.sqltext) == expression
