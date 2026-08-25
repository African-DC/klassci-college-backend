"""Qui voit quoi dans le journal.

Le comptable doit pouvoir remonter un versement contesté jusqu'à la personne
qui l'a saisi. Il n'a pas à lire au passage les notes d'un élève, les
décisions d'un conseil de classe ou les dossiers du personnel. Le
cloisonnement se joue ici, sur une liste d'entités, plutôt qu'en dispersant
des tests de rôle dans les requêtes.
"""

# Tout ce qui touche à l'argent : versements, grille tarifaire, échéanciers,
# caisses. C'est exactement le périmètre du comptable.
FINANCIAL_ENTITIES = frozenset(
    {
        "payment",
        "cash_session",
        "fee_category",
        "fee_variant",
        "fee_installment_grid",
        "enrollment_installment_plan",
        "optional_fee_option",
        "student_option",
    }
)


def visible_entity_types(*, full_access: bool, financial_access: bool) -> frozenset[str] | None:
    """Entités lisibles par l'appelant. `None` signifie « tout le journal ».

    L'accès complet l'emporte : un directeur qui a aussi la vue financière ne
    doit pas se retrouver restreint par la plus étroite des deux permissions.
    """
    if full_access:
        return None
    if financial_access:
        return FINANCIAL_ENTITIES
    return frozenset()
