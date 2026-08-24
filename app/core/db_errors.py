"""Traduction des contraintes de base en messages qui disent quoi faire.

Sans ces traductions, MySQL remonte jusqu'à Starlette qui répond un `500
Internal Server Error` en texte brut. Le texte brut contourne le pipeline
d'erreurs et n'a donc pas les en-têtes CORS : le navigateur bloque la
réponse, et le front n'affiche qu'une erreur réseau générique. La cause est
pourtant parfaitement explicable — un nom déjà pris, un élément encore
utilisé — et l'utilisateur pourrait la corriger seul.
"""

import re

from sqlalchemy.exc import IntegrityError

# Doublon sur un index unique.
_DUPLICATE = (1062,)

# 1451 : on supprime un parent encore référencé.
# 1452 : on crée ou modifie un enfant qui pointe vers un parent absent.
# 1048 : colonne NOT NULL mise à NULL — arrive quand SQLAlchemy tente de
#        détacher les enfants avant un DELETE. Le symptôme diffère, la cause
#        est la même : quelque chose dépend encore de cet élément.
_STILL_REFERENCED = (1451, 1048)
_MISSING_PARENT = (1452,)

# « Duplicate entry 'Inscription' for key 'fee_categories.name' »
_DUPLICATE_ENTRY = re.compile(r"Duplicate entry '([^']*)' for key '([^']*)'")

# Messages sur mesure pour les contraintes composées, où la valeur en cause
# ressemble à « 1-2-3-4 » et ne veut rien dire pour un utilisateur.
_COMPOSITE_MESSAGES = {
    "uq_fee_variant_category_level_series_year": (
        "Un montant est déjà défini pour cette catégorie, ce niveau, cette série "
        "et cette année. Modifiez celui qui existe au lieu d'en créer un second."
    ),
    "uq_fee_installment_year_position": (
        "Cette tranche existe déjà pour l'année scolaire. Rechargez la page : "
        "la grille a probablement été enregistrée entre-temps."
    ),
    "uq_cash_session_cashier_date": (
        "Une journée de caisse est déjà ouverte pour cette personne à cette date."
    ),
    "uq_fee_variant_dimensions": (
        "Un montant est déjà défini pour cette catégorie, ce niveau, cette série, "
        "cette année et ce statut d'affectation. Modifiez celui qui existe au lieu "
        "d'en créer un second."
    ),
}


def _errno(exc: IntegrityError) -> int | None:
    args = getattr(exc.orig, "args", None)
    if args and isinstance(args[0], int):
        return args[0]
    return None


def _duplicate_message(exc: IntegrityError) -> str:
    found = _DUPLICATE_ENTRY.search(str(exc.orig))
    if not found:
        return "Cet enregistrement existe déjà."

    value, key = found.group(1), found.group(2)
    index_name = key.rsplit(".", 1)[-1]

    if index_name in _COMPOSITE_MESSAGES:
        return _COMPOSITE_MESSAGES[index_name]

    # C'est l'INDEX qui dit s'il y a un nom à changer, pas la forme de la
    # valeur. Deviner d'après la valeur se trompe dans les deux sens : une clé
    # composée « 1-1-1-0-affecte » porte des lettres et passait pour un nom,
    # tandis qu'un nom comme « 2024-2025 » ne porte que des chiffres et passait
    # pour une clé composée. Dans les deux cas l'utilisateur lisait une consigne
    # inapplicable.
    if "name" in index_name.lower():
        return f"« {value} » existe déjà. Choisissez un autre nom."

    return (
        "Cet enregistrement existe déjà avec la même combinaison de valeurs. "
        "Modifiez celui qui existe au lieu d'en créer un second."
    )


def integrity_error_message(exc: IntegrityError) -> tuple[int, str, str]:
    """Renvoie (code HTTP, message pour l'utilisateur, code machine)."""
    errno = _errno(exc)

    if errno in _DUPLICATE:
        return 409, _duplicate_message(exc), "DUPLICATE"

    if errno in _STILL_REFERENCED:
        return (
            409,
            "Impossible de supprimer cet élément : il est encore utilisé ailleurs. "
            "Retirez d'abord ce qui en dépend.",
            "IN_USE",
        )

    if errno in _MISSING_PARENT:
        # Distinct du précédent : ici on crée, on ne supprime pas. Annoncer
        # « impossible de supprimer » à quelqu'un qui vient de cliquer sur
        # Enregistrer le laisse perplexe.
        return (
            409,
            "L'élément auquel vous rattachez cet enregistrement n'existe plus. "
            "Rechargez la page et réessayez.",
            "MISSING_PARENT",
        )

    return 409, "L'opération viole une contrainte de la base de données.", "CONSTRAINT"
