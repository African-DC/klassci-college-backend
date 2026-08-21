"""Quelle caisse l'appelant a-t-il le droit de lire.

Une seule règle, écrite une seule fois, utilisée par la liste et par les deux
exports. C'est volontairement minuscule : c'est la pièce qui décide si une
caissière peut voir l'argent encaissé par sa collègue, et une pièce de cette
nature doit tenir dans un regard et se tester seule.

La matrice des rôles (`app.services.tenants.permissions`) prive délibérément le
caissier de `payments:read:all`. Ici on ne fait qu'en tirer la conséquence,
sans jamais nommer un rôle : `if role == "cashier"` serait une permission en
dur, et le jour où l'établissement crée un poste de guichet supplémentaire,
personne ne penserait à revenir modifier cette ligne.
"""

from __future__ import annotations


def cashier_scope(
    *,
    requested_received_by: int | None,
    can_read_all: bool,
    current_user_id: int,
) -> int | None:
    """Renvoie l'identifiant de caisse à appliquer en filtre, ou `None` pour tout.

    Sans `payments:read:all`, l'appelant est ramené à sa propre caisse — y
    compris s'il demande explicitement celle d'un collègue. Un filtre est une
    commodité de lecture ; il ne peut pas servir de passe-droit.

    Avec `payments:read:all`, le filtre demandé est respecté tel quel : c'est
    la comptabilité qui isole la caisse d'une personne pour la contrôler.
    """
    if not can_read_all:
        return current_user_id
    return requested_received_by
