"""Un élève porte la forme comparable de son nom, au lieu qu'on la recalcule.

La recherche de doublons repliait les accents et la ponctuation dans la requête
elle-même : 54 `replace()` imbriqués, répliqués quatre fois dans le même arbre
d'analyse, soit 216 appels dans le SQL compilé.

Cette requête était illisible, inutilisable par un index, et la CI l'a refusée
net le 2026-08-27 (run 33086041547) : `sqlite3.OperationalError: parser stack
overflow`, vingt tests tombés. Elle passe pourtant sur d'autres builds de
SQLite, dont celui du poste de développement — la pile d'analyse grandit
dynamiquement chez les uns et pas chez les autres. Le repliage était donc au
bord d'une limite qui dépend de la machine, ce qui est pire qu'au-delà.

Ce n'est pas la meilleure raison de stocker cette forme, seulement la plus
bruyante. La vraie : le repliage vivait en deux exemplaires, un en SQL et un en
Python, qui avaient fini par ne plus dire la même chose — un nom enregistré
avec « œ » était introuvable. Écrite une seule fois, à l'écriture, la règle ne
peut plus diverger d'elle-même.

Ce que ces colonnes n'apportent pas : de la vitesse. Le motif compile un
`LIKE '%...%'`, joker en tête, qui reste un balayage. Leurs index ne servent
que la recherche par égalité, celle des noms de trois lettres ou moins — et
même celle-là tombe dès qu'un matricule est saisi en plus du nom, le terme du
matricule étant enveloppé dans un `lower()` qui interdit l'usage de son index
unique. Dette antérieure à cette migration, suivi #344.

ORDRE DE DÉPLOIEMENT — cette migration AVANT le nouveau code, et les deux
rapprochées. Quatre choses peuvent mal tourner.

UNE BASE PAR ÉTABLISSEMENT. C'est le piège propre à ce SaaS, et le plus facile
à oublier : la migration doit être jouée sur CHAQUE base de tenant, pas une
fois pour toutes. La CLI n'en migre qu'une à la fois
(`klassci alembic upgrade --tenant <slug>`) et il n'existe pas de commande qui
les parcoure. Sur la production du 2026-08-27 il y en a deux, `local` et
`rostan-bouake` ; les énumérer avec `SHOW DATABASES` en écartant les quatre
bases système. Une base oubliée, c'est le premier cas ci-dessous sur cette
école-là — et sur elle seule, donc personne d'autre ne le signalera.

Code neuf sans la migration. SQLAlchemy énumère toutes les colonnes du modèle
dans chaque `SELECT` : ce n'est donc pas la seule détection de doublon qui
tombe, c'est TOUTE lecture d'élève — la liste, l'inscription, la caisse, les
bulletins, les portails parent et élève. L'application est hors service, pas
diminuée.

Migration sans le code neuf. Les colonnes sont `NOT NULL` sans défaut, et
l'ancien code ne les connaît pas : son `INSERT` échoue avec « Field
'last_name_key' doesn't have a default value ». Le secrétariat ne peut plus
inscrire personne, mais rien de muet n'est enregistré — et c'est la fenêtre à
préférer si l'une des deux doit exister, parce qu'elle se voit tout de suite.
Cette franchise dépend du mode strict de MySQL : hors mode strict, le moteur
insérerait une chaîne vide sans rien dire, et l'élève serait invisible à la
détection. Le compose de production écrit désormais les six modes relevés sur
le serveur, `STRICT_TRANS_TABLES` compris, pour que cette protection cesse
d'être une hypothèse sur le moteur. La démo Windows, elle, s'en remet encore au
défaut de MySQL.

Migration interrompue en cours de route. C'est la seule des quatre dont on ne
sort pas tout seul. Sur MySQL, un `ALTER TABLE` valide implicitement : si le
remplissage échoue après le premier `add_column`, les colonnes restent, leur
défaut serveur vide est toujours actif, aucune clé n'est calculée, et la
révision n'est pas estampillée — un `upgrade` rejoué échouera sur « duplicate
column ». La sortie est manuelle : retirer les deux colonnes, puis rejouer. Le
risque est faible — le remplissage est du Python pur suivi d'un `executemany`,
et la clé ne peut pas dépasser la largeur de la colonne — mais il n'est pas nul,
d'où cette note.

Revision ID: 0075_student_search_key
Revises: 0074_enrol_validate_perm
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.names import compact

revision: str = "0075_student_search_key"
down_revision: str | None = "0074_enrol_validate_perm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LARGEUR = 200


def _remplir(connexion: sa.Connection) -> None:
    """Calcule la clé des fiches existantes, par la fonction Python.

    Pas par du SQL : c'est la seule façon de garantir que les fiches déjà en
    base répondent exactement comme celles qui seront créées ensuite. Un
    repliage SQL écrit ici serait un troisième exemplaire de la règle, et le
    troisième aurait divergé aussi.
    """
    if not isinstance(connexion, sa.Connection):
        # `alembic upgrade --sql` rend du DDL sans se connecter : il fournit ici
        # une connexion factice, incapable de lire une ligne. Le script produit
        # poserait les colonnes avec une chaine vide et n'irait jamais calculer
        # les cles — tout le fichier eleves deviendrait invisible a la
        # detection, sans un mot. Refuser vaut mieux qu'un script faux.
        raise RuntimeError(
            "0075 ne peut pas etre jouee hors ligne : elle doit lire les eleves "
            "existants pour calculer leur cle de recherche. Jouer la migration "
            "en ligne (alembic upgrade head)."
        )
    fiches = connexion.execute(sa.text("SELECT id, last_name, first_name FROM students")).fetchall()
    if not fiches:
        return
    connexion.execute(
        sa.text(
            "UPDATE students SET last_name_key = :nom, first_name_key = :prenom WHERE id = :id"
        ),
        [
            {"nom": compact(nom), "prenom": compact(prenom), "id": identifiant}
            for identifiant, nom, prenom in fiches
        ],
    )


def upgrade() -> None:
    # Le defaut serveur n'existe que pour l'ALTER TABLE sur les lignes deja
    # presentes. Il est retire juste apres : sans ce retrait, un futur INSERT
    # qui oublierait les deux colonnes reussirait en silence avec une cle vide,
    # et l'eleve serait invisible a la detection — exactement le contournement
    # qu'on cherche a rendre impossible.
    op.add_column(
        "students",
        sa.Column("last_name_key", sa.String(length=_LARGEUR), nullable=False, server_default=""),
    )
    op.add_column(
        "students",
        sa.Column("first_name_key", sa.String(length=_LARGEUR), nullable=False, server_default=""),
    )

    _remplir(op.get_bind())

    for colonne in ("last_name_key", "first_name_key"):
        op.alter_column(
            "students",
            colonne,
            existing_type=sa.String(length=_LARGEUR),
            existing_nullable=False,
            server_default=None,
        )

    op.create_index("ix_students_last_name_key", "students", ["last_name_key"])
    op.create_index("ix_students_first_name_key", "students", ["first_name_key"])


def downgrade() -> None:
    op.drop_index("ix_students_first_name_key", table_name="students")
    op.drop_index("ix_students_last_name_key", table_name="students")
    op.drop_column("students", "first_name_key")
    op.drop_column("students", "last_name_key")
