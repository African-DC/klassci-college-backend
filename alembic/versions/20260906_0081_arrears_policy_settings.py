"""Chaque etablissement regle lui-meme ce qu'il fait d'une dette d'un exercice passe.

43 eleves doivent 2 257 000 F sur 2025-2026. Le jour ou ils se reinscrivent en
2026-2027, cette ardoise sort du portail de leur famille — les deux portails
lisent la derniere inscription — et n'apparait sur aucune vue d'ensemble, qui
exige une annee. Aucun chiffre n'est faux : c'est un angle mort.

Ce qu'une ecole fait de cette dette lui appartient. L'une relance et inscrit
quand meme, l'autre conditionne la reinscription. Deux colonnes portent donc ce
choix, sur le singleton `school_settings` qui porte deja une vingtaine de
reglages de meme nature :

- `arrears_policy` — `off`, `inform` ou `block` ;
- `arrears_block_threshold_xof` — le montant a partir duquel `block` refuse.
  `0` refuse au premier franc du, ce qui est le sens litteral du reglage.

LE DEFAUT EST L'IDENTITE

`off` pour tout le monde, ecoles deja en service comprises. Ce n'est pas une
precaution de style : c'est la seule valeur qui garantit qu'une ecole en pleine
rentree ne voit RIEN changer le matin ou son serveur est mis a jour. Avec `off`,
`app/services/arrears_policy.py` rend `None` et le garde sort avant d'avoir
quoi que ce soit a demander a la base — pas de bandeau, pas de refus, pas une
requete de plus.

Ce depot a deja corrige un defaut qui agissait en silence (une valeur par
defaut portait le domaine d'une ecole reelle). Un defaut qui agit est un piege.
Seul un geste dans les reglages leve celui-ci, et ce geste est journalise.

Jouee seule, cette migration est invisible : deux colonnes de plus, a leur
valeur neutre, qu'aucun ecran ne montre encore tant que le code neuf n'est pas
la.

MARCHE A SUIVRE, PRODUCTION DOCKER

Une base par etablissement : c'est le piege propre a ce SaaS. Jouee sur une
seule base, elle laisse les autres ecoles sans les colonnes, et l'endpoint de
reglage y rendrait une erreur SQL des la premiere ouverture de l'ecran.
`migrate_all` les parcourt toutes.

1. Sauvegarder chaque base et verifier que le dump n'est pas vide. Attention,
   `scripts/backup-mysql.sh` ne prend que `local` et les bases nommees
   `klassci_%` : une ecole s'appelle de son slug, `rostan-bouake` n'y entre
   pas. Faire un `mysqldump` nommement.
2. Construire l'image neuve. La revision n'existe que dedans : le `Dockerfile`
   copie `alembic.ini` et `alembic/`, et son `CMD` ne lance qu'uvicorn — rien
   ne migre au demarrage.
3. Jouer la migration depuis un conteneur JETABLE, AVANT de toucher aux
   services vivants :

       cd /etc/dokploy/compose/klassci-college-prod/code
       docker compose -p klassci-college-prod run --rm --no-deps backend python -m app.cli.migrate_all head

   `-p klassci-college-prod` et `--no-deps` ne sont pas du confort : sans `-p`,
   Compose prend le nom du repertoire (`code`) et croit devoir creer sa propre
   pile ; les volumes etant `external`, le mysql neuf s'attacherait aux donnees
   de la production. C'est l'incident du 2026-08-25.

   Controler la ligne « Found N tenant databases » : `information_schema` est
   filtree par privileges, donc une base sur laquelle le compte n'a pas de
   droit est ignoree SANS un mot. Une ecole absente de ce compte est une ecole
   dont l'ecran des reglages tombera en erreur.

   Si `/etc/dokploy` n'est pas lisible par l'utilisateur, passer par la forme
   employee dans `deploy/linux/adopt_dokploy.py` : `docker run --rm -v
   /var/run/docker.sock:/var/run/docker.sock -v <code>:/work -w /work
   docker:27-cli compose -p klassci-college-prod run ...`.
4. NE PASSER A CETTE ETAPE QUE SI L'ETAPE 3 EST SORTIE A ZERO. Recreer les
   TROIS services qui portent cette image — `backend`, `worker` et `beat`.

LES DEUX SENS DE DESYNCHRONISATION

Migration sans le code neuf — inoffensif. Deux colonnes que personne ne lit,
a `off` et `0`.

Code neuf sans la migration — l'ecran des reglages et toute lecture du
singleton tombent sur une colonne inconnue. C'est le sens qui casse, d'ou
l'ordre impose a l'etape 3 : la migration AVANT le redeploiement des services.

Migration interrompue — les deux `ADD COLUMN` sont independants et un
`ALTER TABLE` MySQL n'est pas partiel. Relancer.

Revision ID: 0081_arrears_policy
Revises: 0080_arrears_override
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision: str = "0081_arrears_policy"
down_revision: str | None = "0080_arrears_override"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Les trois valeurs, dans le meme ordre que `ArrearsPolicy`
#: (`app/models/academic.py`). Les tenir alignees est verifie par un test.
_POLITIQUES = ("off", "inform", "block")


def upgrade() -> None:
    op.add_column(
        "school_settings",
        sa.Column(
            "arrears_policy",
            sa.Enum(*_POLITIQUES, name="arrears_policy"),
            nullable=False,
            server_default="off",
        ),
    )
    op.add_column(
        "school_settings",
        sa.Column(
            "arrears_block_threshold_xof",
            # Un montant en francs CFA n'est jamais negatif : MySQL le refuse a
            # la source. Le `with_variant` laisse SQLite, sur lequel tournent
            # les tests, prendre un INTEGER ordinaire.
            sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    # Le downgrade tourne avec le code de la revision precedente, qui ne lit
    # aucune de ces deux colonnes : une ecole qui avait active `block` se
    # retrouve simplement sans politique, donc sans refus. Aucune inscription
    # n'est touchee, aucun versement n'est reecrit.
    #
    # Ce qui se perd, c'est le seuil que la direction avait fixe : le noter
    # avant de redescendre, il n'est nulle part ailleurs.
    op.drop_column("school_settings", "arrears_block_threshold_xof")
    op.drop_column("school_settings", "arrears_policy")
