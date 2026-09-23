"""Figer l'état d'un objet avant qu'on le modifie ou qu'on le supprime.

Sans ces valeurs, le journal ne sait dire que l'après. Une ligne
« Modification · Versement » qui affiche 50 000 sans dire qu'il y en avait
30 000 ne règle aucun litige, et une suppression sans trace de ce qui a
disparu n'est pas rattrapable : la fiche n'existe plus.

Deux partis pris, tous deux contre la tentation du générique.

Les clés sont **nommées une par une** à l'appel. Jamais `dir(obj)`, jamais
`changes.keys()`. Un capteur qui devine ce qu'il faut prendre finit par
prendre `hashed_password` ou la clé API MailPulse, que
`mailpulse/settings_service.py` s'applique justement à tenir hors du journal.
Ici, ce qui entre en base a été tapé par quelqu'un.

`AttributeError` n'est pas rattrapé. Une clé de payload qui ne correspond à
aucun attribut du modèle (`update_room` en a une : `class_id` vit sur
`Class`, pas sur `Room`) est un bug de développement, et il doit tomber en
test, pas écrire un journal silencieusement incomplet.
"""

import enum
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import class_mapper

# Types que la colonne JSON avale tels quels.
_PASSTHROUGH = (str, int, float, bool, type(None))


def json_safe(value: Any) -> Any:
    """Convertit une valeur ORM en quelque chose que la colonne JSON accepte.

    `date`, `Decimal` et les énumérations lèvent un `TypeError` à l'insertion,
    et `audit_log` propage ce TypeError : la requête métier tombe en 500. Le
    piège est documenté dans `grades_service.py`, on le désamorce ici.
    """
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, enum.Enum):
        return json_safe(value.value)
    if isinstance(value, Decimal):
        # Chaîne, pas float : un montant en francs ne doit pas passer par un
        # binaire flottant entre la caisse et le journal.
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, _PASSTHROUGH):
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [json_safe(v) for v in value]
    return str(value)


def frozen_changed(obj: object, changes: dict[str, Any]) -> dict[str, Any]:
    """État actuel des champs que `changes` s'apprête à modifier.

    Pensé pour la forme la plus courante du code : un payload de modification
    validé par Pydantic, dont les clés sont les colonnes à écrire. C'est cette
    provenance qui tient les secrets dehors, et non une liste de noms
    interdits : un champ n'entre ici que si un schéma `*Update` l'expose déjà.

    Les clés qui ne sont pas des colonnes du modèle sont refusées, pas
    ignorées. `update_room` en donne l'exemple : son payload porte `class_id`,
    qui vit sur `Class`, et le service le retire lui-même avant d'arriver ici.
    Un service qui ne l'aurait pas fait doit l'apprendre en test, pas
    journaliser à moitié en silence.
    """
    # `class_mapper` lève de lui-même sur ce qui n'est pas un modèle mappé, et
    # c'est ce qu'on veut : ce helper n'a de sens que sur une ligne de base.
    colonnes = class_mapper(type(obj)).columns
    inconnues = [key for key in changes if key not in colonnes]
    if inconnues:
        raise AttributeError(
            f"{type(obj).__name__} n'a pas les colonnes {inconnues} : "
            "retirez-les du payload avant d'auditer, ou figez les champs à la main."
        )
    return frozen(obj, *changes)


def subject_of(obj: object) -> str | None:
    """Nom lisible d'une fiche déjà chargée : « Aminata Traoré · CI-2026-0012 ».

    Aucune requête, aucune relation suivie : on ne lit que des colonnes
    scalaires de l'objet que l'appelant tient déjà. C'est ce qui permet de
    nommer le sujet du journal sans payer un aller-retour à la base par geste
    audité, y compris dans les boucles d'import ou de levée de zéros.

    Rend `None` quand l'objet n'a rien qui ressemble à un nom. L'écran affiche
    alors le type et l'identifiant, et le dit comme tel.
    """
    prenom = getattr(obj, "first_name", None)
    nom = getattr(obj, "last_name", None)
    if prenom or nom:
        personne = f"{prenom or ''} {nom or ''}".strip()
        matricule = getattr(obj, "enrollment_number", None)
        return f"{personne} · {matricule}" if matricule else personne

    for attribut in ("name", "title", "label", "email"):
        valeur = getattr(obj, attribut, None)
        if isinstance(valeur, str) and valeur.strip():
            return valeur.strip()
    return None


def ref(entity_type: str, entity_id: int | None, label: str | None) -> dict[str, Any] | None:
    """Une fiche liée : `{type, id, label}`, ou rien s'il n'y a ni l'un ni l'autre.

    L'identifiant ouvre la fiche tant qu'elle existe, le libellé reste lisible
    quand elle a disparu.
    """
    if entity_id is None and not label:
        return None
    return {"type": entity_type, "id": entity_id, "label": label}


def frozen(obj: object, *keys: str) -> dict[str, Any]:
    """Valeurs actuelles de `obj` pour les attributs nommés, prêtes pour le JSON.

    À appeler **avant** la mutation, sur un objet déjà chargé : aucune requête
    supplémentaire, aucun accès à une relation paresseuse (qui lèverait le
    `MissingGreenlet` habituel de ce projet).

    Une collection ou une relation passée ici est refusée plutôt que
    sérialisée n'importe comment : on veut une valeur comparable dans la
    colonne « Avant », pas la représentation d'un objet Python.
    """
    snapshot: dict[str, Any] = {}
    for key in keys:
        value = getattr(obj, key)
        if hasattr(value, "_sa_instance_state") or (
            isinstance(value, list | set) and any(hasattr(v, "_sa_instance_state") for v in value)
        ):
            raise TypeError(
                f"{type(obj).__name__}.{key} est une relation : "
                "figez le champ scalaire correspondant (par ex. son identifiant)."
            )
        snapshot[key] = json_safe(value)
    return snapshot
