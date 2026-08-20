"""Contraintes de base traduites en messages lisibles.

Sans ces handlers, MySQL remonte jusqu'à Starlette qui répond un `500
Internal Server Error` en texte brut. Le front n'a plus qu'un « Erreur
serveur » générique, alors que la cause est parfaitement explicable.
"""

from app.core.db_errors import integrity_error_message


class _FakeOrig(Exception):
    def __init__(self, errno: int, message: str) -> None:
        self.args = (errno, message)
        self._message = message

    def __str__(self) -> str:
        return self._message


class _FakeIntegrityError(Exception):
    def __init__(self, errno: int, message: str) -> None:
        self.orig = _FakeOrig(errno, message)


def test_doublon_nomme_la_valeur_en_cause() -> None:
    """« existe déjà » sans dire quoi oblige à deviner."""
    exc = _FakeIntegrityError(
        1062, "(1062, \"Duplicate entry 'Inscription' for key 'fee_categories.name'\")"
    )
    status, detail, code = integrity_error_message(exc)  # type: ignore[arg-type]
    assert status == 409
    assert code == "DUPLICATE"
    assert "Inscription" in detail
    assert "fee_categories" not in detail, "aucun nom de table ne doit fuir à l'écran"


def test_doublon_sans_valeur_lisible_reste_comprehensible() -> None:
    exc = _FakeIntegrityError(1062, "Duplicate entry")
    status, detail, code = integrity_error_message(exc)  # type: ignore[arg-type]
    assert status == 409
    assert code == "DUPLICATE"
    assert "existe déjà" in detail


def test_cle_etrangere_dit_quoi_faire() -> None:
    """« encore utilisé ailleurs » doit venir avec la marche à suivre."""
    exc = _FakeIntegrityError(1451, "Cannot delete or update a parent row")
    status, detail, code = integrity_error_message(exc)  # type: ignore[arg-type]
    assert status == 409
    assert code == "IN_USE"
    assert "utilisé ailleurs" in detail
    assert "Retirez d'abord" in detail


def test_contrainte_inconnue_reste_un_conflit_pas_un_500() -> None:
    exc = _FakeIntegrityError(9999, "something else")
    status, _, code = integrity_error_message(exc)  # type: ignore[arg-type]
    assert status == 409
    assert code == "CONSTRAINT"


def test_erreur_sans_numero_ne_fait_pas_planter_le_handler() -> None:
    class _NoArgs(Exception):
        orig = Exception("boom")

    status, _, code = integrity_error_message(_NoArgs())  # type: ignore[arg-type]
    assert status == 409
    assert code == "CONSTRAINT"


# ---------------------------------------------------------------------------
# Gardes métier — dire ce qui bloque, pas laisser la base répondre
# ---------------------------------------------------------------------------


def test_le_message_de_suppression_dit_combien_et_quoi_faire() -> None:
    """« Impossible de supprimer » sans dire combien ni comment ne débloque
    personne : la secrétaire reste devant son écran."""
    from app.services.fee_service import _blocked_by_variants_message

    single = _blocked_by_variants_message("Tenue scolaire", 1)
    assert "Tenue scolaire" in single
    assert "1 montant configuré" in single
    assert "Supprimez-les d'abord" in single

    plural = _blocked_by_variants_message("Scolarité", 3)
    assert "3 montants configurés" in plural


def test_cle_composee_ne_demande_pas_de_changer_un_nom() -> None:
    """« 1-2-3-4 existe déjà, choisissez un autre nom » : il n'y a aucun nom
    à changer, et l'utilisateur reste bloqué devant son formulaire."""
    exc = _FakeIntegrityError(
        1062,
        "(1062, \"Duplicate entry '1-2-3-4' for key "
        "'fee_variants.uq_fee_variant_category_level_series_year'\")",
    )
    _, detail, code = integrity_error_message(exc)  # type: ignore[arg-type]
    assert code == "DUPLICATE"
    assert "autre nom" not in detail
    assert "catégorie" in detail and "niveau" in detail


def test_creer_avec_un_parent_absent_ne_parle_pas_de_suppression() -> None:
    """Annoncer « impossible de supprimer » a quelqu'un qui vient de cliquer
    sur Enregistrer le laisse perplexe."""
    exc = _FakeIntegrityError(1452, "Cannot add or update a child row")
    _, detail, code = integrity_error_message(exc)  # type: ignore[arg-type]
    assert code == "MISSING_PARENT"
    assert "supprimer" not in detail
    assert "Rechargez la page" in detail


def test_colonne_non_nulle_est_traitee_comme_un_element_encore_utilise() -> None:
    """SQLAlchemy detache les enfants avant un DELETE : le symptome est
    « column cannot be null », la cause est bien une dependance."""
    exc = _FakeIntegrityError(1048, "Column 'fee_category_id' cannot be null")
    _, detail, code = integrity_error_message(exc)  # type: ignore[arg-type]
    assert code == "IN_USE"
    assert "utilisé ailleurs" in detail
