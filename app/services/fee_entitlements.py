"""Contrepartie d'un frais : lecture depuis l'ORM, et rendu court pour un PDF.

Un seul endroit compose la phrase « ce que ce frais ouvre », parce qu'elle est
lue a la caisse, sur le recu, sur l'etat des frais et dans les deux portails.
Le jour ou l'ecole change d'avis sur la formulation, elle change ici.
"""

from __future__ import annotations

from typing import Any

from app.models.fee import FeeEntitlementKind
from app.schemas.fee import FeeEntitlement, coerce_entitlements

#: Budget de caracteres d'une ligne de contrepartie sur un recu. Le recu part
#: en deux exemplaires sur une A4 coupee au milieu : une demi-page fait 148 mm
#: de haut, et chaque ligne mangee ici est une ligne de moins pour la situation
#: financiere de l'eleve. 150 caracteres tiennent sur deux lignes a 7 pt.
RECEIPT_LINE_BUDGET = 150

#: Nombre de categories detaillees sur un recu. Au-dela, on compte le reste.
RECEIPT_MAX_CATEGORIES = 3


def read(category: Any) -> list[FeeEntitlement]:
    """Lit la contrepartie d'une categorie deja chargee, sans requete ni 500.

    Accepte `None` — une variante orpheline de categorie ne doit pas empecher
    une fiche de s'afficher, elle n'a simplement rien a promettre.
    """
    if category is None:
        return []
    brut = getattr(category, "entitlements", None)
    propres = coerce_entitlements(brut)
    lisibles: list[FeeEntitlement] = []
    for element in propres if isinstance(propres, list) else []:
        try:
            lisibles.append(FeeEntitlement.model_validate(element))
        except ValueError:
            # Une ligne mal formee est ignoree : mieux vaut annoncer trois
            # contreparties sur quatre qu'une page d'erreur au secretariat.
            continue
    return lisibles


def _element_text(element: FeeEntitlement) -> str:
    if element.quantity is None:
        return element.label
    return f"{element.quantity} {element.label}"


def _join(elements: list[FeeEntitlement]) -> str:
    return ", ".join(_element_text(e) for e in elements)


def summary(entitlements: list[FeeEntitlement]) -> str:
    """Compose la phrase complete : ce qui se retire, puis ce qui s'ouvre.

    Les deux natures sont annoncees separement parce qu'elles n'engagent pas
    l'ecole de la meme facon. « Remis » est une dette physique dont un parent
    peut revenir reclamer l'execution ; « Acces » est un droit qui ne se
    retire pas au guichet.
    """
    remis = [e for e in entitlements if e.kind == FeeEntitlementKind.ITEM]
    acces = [e for e in entitlements if e.kind == FeeEntitlementKind.ACCESS]
    morceaux: list[str] = []
    if remis:
        morceaux.append(f"Remis : {_join(remis)}")
    if acces:
        morceaux.append(f"Accès : {_join(acces)}")
    return " · ".join(morceaux)


def _tronquer(texte: str, budget: int) -> str:
    """Coupe sur une virgule, jamais au milieu d'un mot.

    Un recu qui annonce « 2 macaro » ne rassure personne. Si rien ne tient,
    on rend une chaine vide plutot qu'un debut de promesse.
    """
    if len(texte) <= budget:
        return texte
    coupe = texte[:budget].rsplit(",", 1)[0].rstrip(" ,·")
    if not coupe or len(coupe) > budget:
        return ""
    return f"{coupe}…"


def receipt_line(entitlements: list[FeeEntitlement], description: str | None = None) -> str:
    """La contrepartie d'une categorie, tenue dans le budget d'un recu.

    Retombe sur la description libre quand aucun element n'est saisi : les
    ecoles deja en production ont ecrit leur contrepartie en texte, et leur
    recu doit la porter des aujourd'hui, sans attendre qu'on ressaisisse tout.
    """
    texte = summary(entitlements)
    if not texte and description:
        texte = " ".join(description.split())
    return _tronquer(texte, RECEIPT_LINE_BUDGET)
