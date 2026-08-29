"""La forme comparable d'un nom d'élève : une seule définition pour la comparaison.

Ce module existe parce que la normalisation était écrite deux fois — une en
Python pour comparer, une en SQL pour présélectionner — et que les deux ont
divergé. Une fiche enregistrée avec « œ » restait introuvable : le SQL dépliait
la ligature, Python non.

La règle est désormais unique et appliquée à l'écriture : un élève porte sa
forme comparable dans ses colonnes `last_name_key` et `first_name_key`, que le
modèle maintient. La lecture n'a plus rien à replier, et ne peut donc plus
replier autrement.

Une exception, et une seule : la console SQL super-admin
(`db_query_service.execute_sql`) écrit en SQL brut, donc hors du modèle. Un
`UPDATE students SET last_name = ...` y laisse la clé sur l'ancienne
orthographe, et l'élève devient introuvable sous son vrai nom. La console
avertit désormais quand une requête écrit un nom sans sa clé
(`STUDENT_NAME_WITHOUT_SEARCH_KEY`), mais elle n'empêche pas : c'est un outil
délibérément sans garde-fous, réservé au super-admin et journalisé. Le dire ici
plutôt que de laisser croire que le modèle couvre tout.

D'autres normalisations de noms subsistent ailleurs (`account_service._slug`
pour fabriquer une adresse e-mail, les generateurs du seed de demonstration).
Elles servent un autre usage et n'ont pas a partager cette regle-ci.

⚠ MODIFIER `normalize()`, `_LIGATURES` OU `compact()` IMPOSE UNE MIGRATION
DE REMPLISSAGE. `normalize()` porte le depliage NFD, le filtrage des
diacritiques et la reduction aux caracteres alphanumeriques ; `compact()`
porte l'ecrasement des espaces, la regle qui fait que « N DRI » vaut
« NDRI ». Les deux comptent, et `_LIGATURES` avec elles.
Les cles deja en base ont ete calculees par la version precedente. Sans
recalcul, les fiches anciennes repondent selon l'ancienne regle et les
nouvelles selon la nouvelle : c'est exactement la divergence que ce module
supprime, replantee sur l'axe du temps. Voir la revision alembic
`0075_student_search_key`, qui montre le remplissage a faire.
"""

from __future__ import annotations

import unicodedata

# Les ligatures ne sont pas des accents : NFD les laisse entières.
_LIGATURES = (("œ", "oe"), ("Œ", "OE"), ("æ", "ae"), ("Æ", "AE"))


def normalize(valeur: str | None) -> str:
    """Réduit un nom à ce qui compte pour la comparaison.

    ⚠ Modifier cette fonction périme toutes les clés déjà en base : voir
        l'avertissement en tête de module, et la révision `0075_student_search_key`
        pour le remplissage à refaire.

        « KOUAMÉ », « kouame » et « Kouamé  » désignent la même personne. Les
        accents sont retirés parce qu'ils sont saisis de façon irrégulière au
        copier-coller, et les traits d'union parce que « MARIE-LINE » et
        « MARIE LINE » s'écrivent au hasard du clavier.
    """
    if not valeur:
        return ""
    deplie = valeur
    for source, cible in _LIGATURES:
        deplie = deplie.replace(source, cible)
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", deplie) if unicodedata.category(c) != "Mn"
    )
    lettres = [c if c.isalnum() else " " for c in sans_accent.lower()]
    return " ".join("".join(lettres).split())


def compact(valeur: str | None) -> str:
    """La forme comparable d'un nom, sans espaces ni ponctuation.

    « N'DRI », « NDRI » et « n dri » doivent se trouver. C'est cette forme
    qu'un élève porte dans ses colonnes `*_key`, et c'est elle que la
    recherche interroge.
    """
    return normalize(valeur).replace(" ", "")
