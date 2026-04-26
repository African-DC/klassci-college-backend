"""Fuzzy search utility — tolerant aux fautes de frappe via RapidFuzz."""

from rapidfuzz import fuzz, process


def fuzzy_filter_by_name(
    items: list,
    search: str,
    *,
    name_getter: callable,
    limit: int = 20,
    score_cutoff: int = 55,
) -> list:
    """Filtre une liste d'objets par similarité fuzzy sur le nom.

    Args:
        items: liste d'objets (SQLAlchemy models)
        search: texte recherché par l'utilisateur
        name_getter: fonction qui extrait le nom complet d'un objet
        limit: nombre max de résultats
        score_cutoff: score minimum (0-100) pour inclure un résultat

    Returns:
        Liste d'objets triés par pertinence (meilleur match en premier)
    """
    if not items or not search:
        return items[:limit]

    # Build {index: full_name} mapping
    choices = {i: name_getter(item) for i, item in enumerate(items)}

    # RapidFuzz extract: returns [(name, score, index), ...]
    matches = process.extract(
        search,
        choices,
        scorer=fuzz.WRatio,
        limit=limit,
        score_cutoff=score_cutoff,
    )

    # Return items sorted by score (highest first)
    return [items[idx] for _, _, idx in matches]
