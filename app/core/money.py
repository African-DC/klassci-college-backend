"""Un montant tel qu'on le lit au guichet : « 25 000 FCFA »."""

from decimal import Decimal


def fcfa(montant: Decimal | int | float) -> str:
    """« 25 000 FCFA ». Le franc CFA n'a pas de centimes : on ne les affiche pas."""
    return f"{Decimal(str(montant)):,.0f} FCFA".replace(",", " ")
