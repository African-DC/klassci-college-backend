"""Les mentions d'État qui coiffent chaque document.

Trois faits institutionnels tenaient sur une seule ligne, en capitales
interlettrées à huit points : la République, la devise et le ministère y
avaient le même poids et la bande se lisait comme un filigrane plutôt que
comme une mention officielle.

Ils sont désormais sur deux niveaux. La République porte le poids — c'est
l'autorité dont le document se réclame. La devise et le ministère suivent en
bas de casse, lisibles sans crier.
"""

from __future__ import annotations

_REPUBLIQUE = "République de Côte d'Ivoire"
_DEVISE = "Union — Discipline — Travail"
_MINISTERE = "Ministère de l'Éducation Nationale et de l'Alphabétisation"


def eyebrow_html() -> str:
    """Le bandeau des mentions d'État, sur deux niveaux."""
    return (
        '<div class="doc-eyebrow">'
        f'<div class="doc-eyebrow-etat">{_REPUBLIQUE}</div>'
        f'<div class="doc-eyebrow-suite">{_DEVISE}'
        f"&nbsp; · &nbsp;{_MINISTERE}</div>"
        "</div>"
    )
