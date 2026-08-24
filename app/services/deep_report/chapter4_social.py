"""Chapitre IV — cas sociaux : tableaux 24 à 27.

Décès, grossesses, maladies et handicaps. Ces informations relèvent du secret
médical et de la vie privée des familles : leur collecte fait l'objet d'un lot
séparé, avec ses propres règles d'accès et de conservation. KLASSCI ne les
stocke pas aujourd'hui.

Les quatre grilles restent imprimées, à l'identique du canevas, pour que le
chef d'établissement les remplisse à la main sans avoir à redessiner un
tableau. Elles portent la mention « à compléter » : un tableau vide sans
mention se lirait comme « aucun cas », affirmation que personne ici n'est en
mesure de faire.
"""

from __future__ import annotations

from app.services.deep_report._types import (
    PENDING_NOTE,
    ReportChapter,
    ReportTable,
    simple_headers,
)

_PRIVACY_NOTE = (
    "Ces informations, sensibles, ne sont pas enregistrées dans KLASSCI. "
    f"{PENDING_NOTE} sur le document imprimé."
)

_EMPTY = f"{PENDING_NOTE} — aucune donnée n'est collectée pour ce tableau."


def build(_context: object) -> ReportChapter:
    """Assemble les quatre grilles vierges du chapitre IV."""
    return ReportChapter(
        title="Chapitre IV — Cas sociaux",
        intro=(
            "Les quatre tableaux de ce chapitre sont fournis vierges : les données de "
            "santé et de vie privée qu'ils appellent ne sont pas collectées par la "
            "plateforme."
        ),
        tables=(
            ReportTable(
                number=24,
                title="Décès",
                groups=simple_headers(
                    "N°",
                    "Nom et Prénoms",
                    "Classe",
                    "Date du décès",
                    "Observations",
                ),
                pending=True,
                note=_PRIVACY_NOTE,
                empty_message=_EMPTY,
            ),
            ReportTable(
                number=25,
                title="Grossesses",
                groups=simple_headers(
                    "N°",
                    "Nom et Prénoms",
                    "Classe",
                    "Âge",
                    "Auteur de la grossesse",
                    "Profession de l'auteur",
                    "Observations",
                ),
                pending=True,
                note=_PRIVACY_NOTE,
                empty_message=_EMPTY,
            ),
            ReportTable(
                number=26,
                title="Maladies",
                groups=simple_headers(
                    "N°",
                    "Nom et Prénoms",
                    "Classe",
                    "Nature de la maladie",
                    "Période",
                    "Observations",
                ),
                pending=True,
                note=_PRIVACY_NOTE,
                empty_message=_EMPTY,
            ),
            ReportTable(
                number=27,
                title="Handicaps",
                groups=simple_headers(
                    "N°",
                    "Nom et Prénoms",
                    "Classe",
                    "Nature du handicap",
                    "Prise en charge",
                    "Observations",
                ),
                pending=True,
                note=_PRIVACY_NOTE,
                empty_message=_EMPTY,
            ),
        ),
    )
