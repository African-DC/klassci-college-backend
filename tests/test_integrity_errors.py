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


def test_un_nom_a_tiret_reste_traite_comme_un_nom() -> None:
    """« Jean-Baptiste » contient un tiret sans être une clé composée : se fier
    à la forme de la valeur aurait produit le mauvais message."""
    exc = _FakeIntegrityError(
        1062, "Duplicate entry 'Jean-Baptiste' for key 'fee_categories.name'"
    )
    _, detail, _ = integrity_error_message(exc)  # type: ignore[arg-type]
    assert "Jean-Baptiste" in detail
    assert "autre nom" in detail


def test_une_cle_composee_inconnue_ne_parle_pas_de_nom() -> None:
    """Un index compose qu'on n'a pas nomme explicitement doit quand meme
    produire un message qui ne demande pas l'impossible."""
    exc = _FakeIntegrityError(
        1062, "Duplicate entry '1-1-1-0-affecte' for key 'fee_variants.uq_quelque_chose'"
    )
    _, detail, _ = integrity_error_message(exc)  # type: ignore[arg-type]
    assert "autre nom" not in detail
    assert "combinaison de valeurs" in detail


def test_la_cle_des_tarifs_a_son_message_dedie() -> None:
    exc = _FakeIntegrityError(
        1062, "Duplicate entry '1-1-1-0-affecte' for key 'fee_variants.uq_fee_variant_dimensions'"
    )
    _, detail, _ = integrity_error_message(exc)  # type: ignore[arg-type]
    assert "portée" in detail and "niveau" in detail
