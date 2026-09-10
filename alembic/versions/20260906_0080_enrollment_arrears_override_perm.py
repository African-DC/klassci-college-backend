"""Passer outre un blocage pour dette devient un droit qu'on peut confier.

43 eleves doivent 2 257 000 F sur l'exercice 2025-2026. Des qu'ils se
reinscrivent en 2026-2027, cette dette sort du portail de leur famille et
n'apparait sur aucune vue d'ensemble : les deux portails lisent la derniere
inscription, la vue d'ensemble exige une annee. La suite de l'issue #447 pose
un reglage par etablissement, puis, quand l'ecole l'a active, un blocage a la
reinscription d'un debiteur.

Ce droit vient AVANT ce blocage, et l'ordre n'est pas negociable. Un garde
pose sans lui refuserait tout le monde, direction comprise, et la seule issue
pour une ecole coincee en pleine rentree serait de desactiver la politique
entiere — c'est-a-dire de perdre la mesure qu'elle venait d'activer.

Le droit est seme aux roles qui detiennent deja `documents:release:override`,
porte en production par `admin` et `director` exclusivement. Meme public, meme
raison : celui qui constate la dette ne doit pas etre celui qui l'efface. Ce
n'est pas pour autant le meme droit, et les deux ne sont surtout pas fusionnes
— `documents:release:override` est circonscrit a la retenue d'UN document. Les
confondre donnerait a qui debloque un bulletin le droit d'inscrire un
debiteur, et l'inverse. Deux gestes, deux droits.

`_seed_permissions_and_roles` (`app/services/tenants/provisioning.py`) ne joue
qu'au provisionnement d'un tenant neuf : sans cette migration, le slug
n'existerait sur aucune ecole deja ouverte, et l'ecran des roles ne le
proposerait nulle part.

Jouee seule, cette migration est invisible : elle ajoute une ligne au
catalogue des permissions et une par role deja habilite a deroger. Elle ne
bloque rien et ne retire rien a personne.

MARCHE A SUIVRE, PRODUCTION DOCKER

Une base par etablissement : c'est le piege propre a ce SaaS. Jouee sur une
seule base, elle laisse les autres ecoles sans le slug, et le blocage de
l'etape suivante y deviendrait infranchissable. `migrate_all` les parcourt
toutes.

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
   qui n'aura pas le droit.

   Si `/etc/dokploy` n'est pas lisible par l'utilisateur, passer par la forme
   employee dans `deploy/linux/adopt_dokploy.py` : `docker run --rm -v
   /var/run/docker.sock:/var/run/docker.sock -v <code>:/work -w /work
   docker:27-cli compose -p klassci-college-prod run ...`.
4. NE PASSER A CETTE ETAPE QUE SI L'ETAPE 3 EST SORTIE A ZERO. Recreer les
   TROIS services qui portent cette image — `backend`, `worker` et `beat`.

LES DEUX SENS DE DESYNCHRONISATION

Migration sans le code neuf — inoffensif. Le slug existe en base, aucun
endpoint ne le demande, l'ecran des roles affiche une case de plus.

Code neuf sans la migration — inoffensif tant que le blocage n'est pas livre,
et c'est precisement pourquoi ce pas passe en premier. Le jour ou le garde
arrive, l'inverse serait vrai : une ecole ayant active la politique sans le
droit en base n'aurait plus personne pour deroger.

Migration interrompue — deux `INSERT IGNORE`, rejouables sans effet.

Revision ID: 0080_arrears_override
Revises: 0079_allocation_uniqueness
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0080_arrears_override"
down_revision: str | None = "0079_allocation_uniqueness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SLUG = "enrollments:arrears:override"
_NOM = "Enrol a student despite arrears"

# Seme depuis ce droit-la, et non depuis `enrollments:create` : le public vise
# est la direction, pas tout guichet capable de monter un dossier. En
# production, `documents:release:override` n'est porte que par `admin` et
# `director` — semer depuis lui vise exactement ce public, sans nommer un role
# dans du SQL.
_SOURCE_SLUG = "documents:release:override"


def upgrade() -> None:
    op.execute(f"INSERT IGNORE INTO permissions (slug, name) VALUES ('{_SLUG}', '{_NOM}')")

    op.execute(
        f"""
        INSERT IGNORE INTO role_permissions (role_id, permission_id)
        SELECT rp.role_id, p_new.id
        FROM role_permissions rp
        JOIN permissions p_old ON p_old.id = rp.permission_id
        CROSS JOIN permissions p_new
        WHERE p_old.slug = '{_SOURCE_SLUG}'
        AND p_new.slug = '{_SLUG}'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE rp FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.id
        WHERE p.slug = '{_SLUG}'
        """
    )
    op.execute(f"DELETE FROM permissions WHERE slug = '{_SLUG}'")
