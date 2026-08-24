"""Les phrases que porte l'en-tête d'un journal des versements.

Un document exporté sans dire ce qu'il contient est un piège : deux tirages du
même écran, à deux filtres différents, sont indiscernables une fois imprimés.
L'en-tête doit donc nommer la période, les filtres et le périmètre — et ne
nommer que ce qui a réellement été appliqué à la requête.

Fonctions pures, sans base de données : elles se lisent et se testent seules.
"""

from __future__ import annotations

from datetime import datetime

from app.services.pdf.theme import method_label, status_label

#: Ce qu'on écrit quand rien ne borne la période.
ALL_PERIODS = "Toutes périodes"
#: Ce qu'on écrit quand l'appelant lit toutes les caisses.
ALL_CASHIERS = "Toutes les caisses"


def _jour(moment: datetime) -> str:
    return moment.strftime("%d/%m/%Y")


def period_label(date_from: datetime | None, date_to: datetime | None) -> str:
    """Décrit la période couverte, telle qu'elle a été appliquée."""
    if date_from is not None and date_to is not None:
        return f"Du {_jour(date_from)} au {_jour(date_to)}"
    if date_from is not None:
        return f"À partir du {_jour(date_from)}"
    if date_to is not None:
        return f"Jusqu'au {_jour(date_to)}"
    return ALL_PERIODS


def filters_label(*, status: str | None, method: str | None) -> str:
    """Énumère les filtres appliqués, ou renvoie une chaîne vide.

    Une chaîne vide se lit « aucun filtre » à l'affichage, ce qui est exact.
    On n'y met que des critères réellement passés à la requête : annoncer un
    filtre qui n'a pas porté ferait mentir le document.
    """
    parts: list[str] = []
    if status:
        parts.append(f"État : {status_label(status)}")
    if method:
        parts.append(f"Moyen de paiement : {method_label(method)}")
    return " · ".join(parts)


def scope_label(*, restricted: bool, cashier_name: str | None) -> str:
    """Dit de quelle caisse parle le document.

    Sur un export cloisonné, c'est la ligne la plus importante de l'en-tête :
    elle empêche de prendre le journal d'un guichet pour celui de l'école.
    """
    if cashier_name:
        prefix = "Ma caisse" if restricted else "Caisse"
        return f"{prefix} — {cashier_name}"
    if restricted:
        return "Ma caisse"
    return ALL_CASHIERS
