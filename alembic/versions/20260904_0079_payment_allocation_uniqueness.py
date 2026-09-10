"""Un frais, une allocation par versement — l'invariant descend enfin en base.

## Ce que cette migration ferme

Le point par catégorie ne lit QUE `payment_allocations` : il ne regarde jamais
`payments.amount`. La phrase « la somme des allocations vaut exactement le
versement » vivait pourtant dans un docstring du modèle, et nulle part ailleurs.
Un versement mal ventilé sortait donc de tous les totaux par catégorie sans
qu'aucun signal ne le dise, pendant que le journal de caisse continuait, lui, de
le compter. Deux chiffres justes qui divergent sans explication détruisent la
confiance dans les deux.

La contrainte posée ici ferme le cas que la somme seule ne voit pas : DEUX
lignes pour le même frais sur le même versement. Elles s'additionnent
correctement, le total tombe juste, et rien ne dit pourquoi elles sont deux —
ni laquelle annuler le jour où l'on rembourse.

## Ce qu'elle n'est PAS

Ce n'est pas un correctif : c'est un filet. Un seul site construit une
allocation (`payment_repository.create_allocation`), le backfill de la
migration 0028 a écrit une ligne par versement, et les deux chemins
d'enregistrement refusent le trop-perçu. La contrainte devrait donc poser sans
rien rencontrer. Si elle rencontre quelque chose, c'est une information à part
entière, et la migration s'arrête en le nommant.

## Elle refuse plutôt que de fusionner, et c'est délibéré

Fusionner deux allocations en sommant leurs montants ne changerait aucun total
— toutes les lectures les additionnent déjà. Mais deux lignes là où le
programme n'en écrit qu'une veut dire que quelque chose a écrit de l'argent
autrement que par le guichet, et une migration n'a pas à normaliser en silence
une écriture qu'on ne s'explique pas. Elle nomme les versements concernés et
laisse un comptable décider. La 0062, qui fusionnait bel et bien, le faisait
sur des lignes de DETTE en double — une dette doublée est fausse par nature. De
l'argent reçu, non.

## MARCHE À SUIVRE, PRODUCTION DOCKER

**ÉTAPE 0, PROPRE À CETTE MIGRATION.** Passer l'audit AVANT de migrer, depuis
un conteneur jetable de l'image neuve — la commande n'existe que dedans :

    cd /etc/dokploy/compose/klassci-college-prod/code
    docker compose -p klassci-college-prod run --rm --no-deps backend \
      python -m app.cli.check_allocations

Elle est en LECTURE SEULE et parcourt toutes les bases. Sortie à 0 : la
contrainte posera. Sortie à 1 : elle listera les versements en cause, et c'est
exactement ceux sur lesquels la migration s'arrêterait — les traiter d'abord,
avec un comptable. `--tenant <slug>` restreint à une école.

Si `/etc/dokploy` n'est pas lisible par l'utilisateur, passer par la forme
employée dans `deploy/linux/adopt_dokploy.py` : `docker run --rm -v
/var/run/docker.sock:/var/run/docker.sock -v <code>:/work -w /work
docker:27-cli compose -p klassci-college-prod run ...`.

Ensuite, la marche habituelle, dans cet ordre :

1. Sauvegarder chaque base et vérifier que le dump n'est pas vide. Attention,
   `scripts/backup-mysql.sh` ne prend que `local` et les bases nommées
   `klassci_%` : une école s'appelle de son slug, `rostan-bouake` n'y entre
   pas. Faire un `mysqldump` nommément.
2. Construire l'image neuve. La révision n'existe que dedans : le `Dockerfile`
   copie `alembic.ini` et `alembic/`, et son `CMD` ne lance qu'uvicorn — rien
   ne migre au démarrage.
3. Jouer la migration depuis un conteneur JETABLE, AVANT de toucher aux
   services vivants :

       docker compose -p klassci-college-prod run --rm --no-deps backend \
         python -m app.cli.migrate_all head

   `-p klassci-college-prod` et `--no-deps` ne sont pas du confort : sans `-p`,
   Compose prend le nom du répertoire (`code`) et croit devoir créer sa propre
   pile ; les volumes étant `external`, le mysql neuf s'attacherait aux données
   de la production. C'est l'incident du 2026-08-25.

   Contrôler la ligne « Found N tenant databases » : `information_schema` est
   filtrée par privilèges, donc une base sur laquelle le compte n'a pas de
   droit est ignorée SANS un mot.
4. NE PASSER À CETTE ÉTAPE QUE SI L'ÉTAPE 3 EST SORTIE À ZÉRO. Recréer les
   TROIS services qui portent cette image — `backend`, `worker` et `beat`.

## LES DEUX SENS DE DÉSYNCHRONISATION

**Migration sans le code neuf** — inoffensif. L'ancien code écrit déjà une
allocation par frais et par versement ; la contrainte ne le gêne pas.

**Code neuf sans la migration** — inoffensif aussi, et c'est pourquoi l'ordre
compte moins ici qu'en 0075. Le modèle déclare la contrainte, mais SQLAlchemy
ne la vérifie pas côté Python : rien ne casse. La vérification à l'écriture,
elle, est purement applicative et fonctionne sans la contrainte. On perd
seulement le filet du dernier ressort.

**Migration interrompue** — `ALTER TABLE` valide implicitement, mais il n'y a
ici qu'une seule instruction : soit l'index est posé, soit il ne l'est pas.
Rejouer est sans effet, la pose étant conditionnée à l'absence de l'index.

Revision ID: 0079_allocation_uniqueness
Revises: 0078_enrollment_history
Create Date: 2026-09-04
"""

import logging
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision: str = "0079_allocation_uniqueness"
down_revision: str | None = "0078_enrollment_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "payment_allocations"
_INDEX = "uq_payment_allocation"

#: Combien de versements en double on nomme avant d'abréger. Au-delà, la liste
#: cesse d'aider : ce n'est plus un incident, c'est un chemin d'écriture à
#: retrouver, et l'audit le listera en entier.
_A_NOMMER = 20


def _has_index(bind) -> bool:
    return bool(
        bind.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i"
            ),
            {"t": _TABLE, "i": _INDEX},
        ).scalar()
    )


def _doublons(bind) -> list[tuple[int, int, int]]:
    """Les couples (versement, frais) écrits plus d'une fois."""
    return [
        (int(versement), int(frais), int(combien))
        for versement, frais, combien in bind.execute(
            text(
                f"""
                SELECT payment_id, enrollment_fee_id, COUNT(*) AS combien
                FROM {_TABLE}
                GROUP BY payment_id, enrollment_fee_id
                HAVING COUNT(*) > 1
                ORDER BY payment_id
                """
            )
        ).fetchall()
    ]


def upgrade() -> None:
    bind = op.get_bind()

    if _has_index(bind):
        # Rejouable sans effet : l'index est déjà là, il n'y a rien à faire et
        # rien à vérifier — sa seule présence prouve qu'il n'y a pas de doublon.
        return

    doublons = _doublons(bind)
    if doublons:
        # S'arrêter EN NOMMANT, plutôt que de laisser MySQL répondre « Duplicate
        # entry '412-38' for key 'uq_payment_allocation' » : cette valeur-là ne
        # désigne rien pour la personne qui lit la sortie du déploiement, et
        # elle n'en tire aucun geste.
        nommes = "; ".join(
            f"versement {versement} × frais {frais} ({combien} lignes)"
            for versement, frais, combien in doublons[:_A_NOMMER]
        )
        reste = len(doublons) - _A_NOMMER
        suite = f" ; et {reste} autre(s)" if reste > 0 else ""
        raise RuntimeError(
            f"{len(doublons)} imputation(s) en double empêchent de poser "
            f"{_INDEX} : {nommes}{suite}. Aucune n'a été touchée — de l'argent "
            f"reçu ne se normalise pas sans qu'un comptable ait tranché. "
            f"Passer `python -m app.cli.check_allocations` pour la liste "
            f"complète, décider ligne par ligne, puis rejouer cette migration."
        )

    op.create_unique_constraint(_INDEX, _TABLE, ["payment_id", "enrollment_fee_id"])
    logger.info("Contrainte %s posee sur %s.", _INDEX, _TABLE)


def downgrade() -> None:
    bind = op.get_bind()
    if _has_index(bind):
        op.drop_constraint(_INDEX, _TABLE, type_="unique")
