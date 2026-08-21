"""Nommer la personne qui a encaissé.

Dans une caisse d'école, la question posée à une ligne de versement n'est pas
« quel identifiant » mais « qui ». Un tableau qui affiche `12` ne répond pas,
et un tableau qui affiche une case vide répond encore moins : au moment d'un
contrôle, c'est précisément cette colonne qu'on relit.

D'où l'ordre de repli : le nom du profil, puis la partie gauche de l'adresse
e-mail — imparfaite mais identifiante — puis un tiret cadratin explicite quand
le compte a réellement disparu. Jamais `None`, jamais une chaîne vide.
"""

from __future__ import annotations

from typing import Any

from app.repositories.user_repository import get_user_full_name

#: Ce que porte une ligne dont l'encaisseur n'est plus identifiable. Le
#: versement, lui, reste : il a été compté, et les bordereaux déjà signés le
#: disent.
UNKNOWN_CASHIER = "—"


def cashier_name(user: Any | None) -> str | None:
    """Nom lisible de l'encaisseur, ou `None` si aucun compte n'est rattaché.

    `None` et `UNKNOWN_CASHIER` disent deux choses différentes, et les
    confondre serait une perte d'information : le premier signifie « ce
    versement ne porte aucun encaisseur », le second « le compte existait mais
    n'est plus lisible ». Le premier est un trou de saisie à corriger, le
    second une trace d'histoire.
    """
    if user is None:
        return None

    first_name, last_name = get_user_full_name(user)
    complet = " ".join(part for part in (first_name, last_name) if part).strip()
    if complet:
        return complet

    email = getattr(user, "email", None) or ""
    local = email.split("@")[0].strip()
    return local or UNKNOWN_CASHIER


def cashier_label(user: Any | None) -> str:
    """Comme `cashier_name`, mais toujours imprimable dans un document."""
    return cashier_name(user) or UNKNOWN_CASHIER
