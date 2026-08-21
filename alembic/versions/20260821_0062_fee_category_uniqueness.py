"""Une categorie de frais, une seule ligne par inscription — enfin garanti par la base.

## Ce que la migration 0060 n'a pas repare

0060 groupait les doublons sur `(enrollment_id, fee_variant_id)`. Elle a donc
soigne les sequelles de 0052 — deux lignes devenues identiques apres que les
tarifs en double eurent ete fusionnes — et laisse intactes celles du bug
qu'elle accompagnait.

Ce bug-la produisait deux lignes de **variantes differentes** pour la meme
categorie : la Scolarite generique ET la Scolarite affectee, parce que la
resolution retenait les deux au lieu de la plus specifique. Deux variantes
differentes font deux groupes : aucune fusion. Sur un locataire touche, l'eleve
affecte porte toujours sa dette doublee, son echeancier double, et le certificat
de scolarite de sa famille reste retenu pour un impaye qui n'existe pas.

## Le remede

On groupe cette fois sur la CATEGORIE, en joignant les tarifs. On garde la
ligne qui porte le plus d'allocations de versement — celle a laquelle
l'argent est deja rattache — et a defaut la plus ancienne. Les allocations et
les rares versements 1:1 d'avant la migration 0028 sont repointes vers elle
avant toute suppression : la cle etrangere est en RESTRICT, une doublure encore
referencee bloquerait la migration entiere.

Aucun versement ne perd sa contrepartie. Le total impute peut alors depasser le
montant de la ligne conservee, si la famille a paye sur les deux : ce
trop-percu n'est pas cree ici, il existait deja, reparti sur deux dettes dont
une seule etait due. Le compte et le montant de dette retiree sont journalises
pour que la caisse puisse les reprendre.

## L'invariant

« Une categorie, une ligne » ne vivait que dans une fonction Python, et il
existe deux chemins d'insertion. On le pose donc en base : une colonne
`fee_category_id` sur `enrollment_fees` et une contrainte unique
`(enrollment_id, fee_category_id)`.

MySQL n'accepte pas de colonne generee ici : une expression STORED ne peut lire
que les colonnes de sa propre ligne, or la categorie vit sur `fee_variants`. La
colonne est donc reelle, renseignee par les deux chemins d'ecriture, et
declaree NOT NULL : un troisieme chemin qui l'oublierait echouerait bruyamment
au lieu de recreer silencieusement le doublon.

Rejouable sans effet : une base deja fusionnee ne presente plus de doublon, et
la colonne comme l'index ne sont poses que s'ils manquent.

Revision ID: 0062_fee_category_uniqueness
Revises: 0061_school_life_reference_width
Create Date: 2026-08-21
"""

import logging

from sqlalchemy import text

from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

revision = "0062_fee_category_uniqueness"
down_revision = "0061_school_life_reference_width"
branch_labels = None
depends_on = None

_TABLE = "enrollment_fees"
_COLUMN = "fee_category_id"
_INDEX = "uq_enrollment_fee_category"
_FK = "fk_enrollment_fees_fee_category"

#: La ligne conservee de chaque couple (inscription, categorie) : celle qui
#: porte le plus d'allocations, et a egalite la plus ancienne.
_KEPT_PER_CATEGORY = """
    INSERT INTO _ef_kept (keep_id, enrollment_id, fee_category_id)
    SELECT classe.id, classe.enrollment_id, classe.fee_category_id
    FROM (
        SELECT ef.id, ef.enrollment_id, fv.fee_category_id,
               ROW_NUMBER() OVER (
                   PARTITION BY ef.enrollment_id, fv.fee_category_id
                   ORDER BY COUNT(pa.id) DESC, ef.id ASC
               ) AS rang
        FROM enrollment_fees ef
        JOIN fee_variants fv ON fv.id = ef.fee_variant_id
        LEFT JOIN payment_allocations pa ON pa.enrollment_fee_id = ef.id
        GROUP BY ef.id, ef.enrollment_id, fv.fee_category_id
    ) classe
    WHERE classe.rang = 1
"""


def _has(bind, requete: str, **params: object) -> bool:
    return bool(bind.execute(text(requete), params).scalar())


def _has_column(bind) -> bool:
    return _has(
        bind,
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = :t AND column_name = :c",
        t=_TABLE,
        c=_COLUMN,
    )


def _has_index(bind) -> bool:
    return _has(
        bind,
        "SELECT COUNT(*) FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i",
        t=_TABLE,
        i=_INDEX,
    )


def _has_fk(bind) -> bool:
    return _has(
        bind,
        "SELECT COUNT(*) FROM information_schema.table_constraints "
        "WHERE table_schema = DATABASE() AND table_name = :t AND constraint_name = :c",
        t=_TABLE,
        c=_FK,
    )


def _merge_duplicates(bind) -> None:
    """Ramene chaque categorie a une seule ligne par inscription."""
    bind.execute(text("DROP TEMPORARY TABLE IF EXISTS _ef_kept"))
    bind.execute(
        text(
            """
            CREATE TEMPORARY TABLE _ef_kept (
                keep_id BIGINT NOT NULL,
                enrollment_id BIGINT NOT NULL,
                fee_category_id BIGINT NOT NULL,
                PRIMARY KEY (enrollment_id, fee_category_id)
            ) ENGINE=InnoDB
            """
        )
    )
    bind.execute(text(_KEPT_PER_CATEGORY))

    # Ce qu'on s'apprete a retirer, mesure AVANT la suppression : une fois les
    # lignes parties, leur montant n'est plus lisible.
    mesure = bind.execute(
        text(
            """
            SELECT COUNT(*) AS lignes, COALESCE(SUM(ef.amount), 0) AS dette
            FROM enrollment_fees ef
            JOIN fee_variants fv ON fv.id = ef.fee_variant_id
            JOIN _ef_kept k
              ON k.enrollment_id = ef.enrollment_id
             AND k.fee_category_id = fv.fee_category_id
            WHERE ef.id <> k.keep_id
            """
        )
    ).one()

    # Repointer les allocations de versement vers la ligne conservee. Avant la
    # suppression : la cle etrangere est en RESTRICT.
    deplacees = bind.execute(
        text(
            """
            UPDATE payment_allocations pa
            JOIN enrollment_fees dup ON dup.id = pa.enrollment_fee_id
            JOIN fee_variants fv ON fv.id = dup.fee_variant_id
            JOIN _ef_kept k
              ON k.enrollment_id = dup.enrollment_id
             AND k.fee_category_id = fv.fee_category_id
            SET pa.enrollment_fee_id = k.keep_id
            WHERE pa.enrollment_fee_id <> k.keep_id
            """
        )
    ).rowcount

    # Meme geste sur la colonne 1:1 d'avant la migration 0028 : plus personne
    # ne l'ecrit, mais les vieilles lignes la renseignent encore et sa cle
    # etrangere est en RESTRICT elle aussi.
    bind.execute(
        text(
            """
            UPDATE payments p
            JOIN enrollment_fees dup ON dup.id = p.enrollment_fee_id
            JOIN fee_variants fv ON fv.id = dup.fee_variant_id
            JOIN _ef_kept k
              ON k.enrollment_id = dup.enrollment_id
             AND k.fee_category_id = fv.fee_category_id
            SET p.enrollment_fee_id = k.keep_id
            WHERE p.enrollment_fee_id <> k.keep_id
            """
        )
    )

    retirees = bind.execute(
        text(
            """
            DELETE dup FROM enrollment_fees dup
            JOIN fee_variants fv ON fv.id = dup.fee_variant_id
            JOIN _ef_kept k
              ON k.enrollment_id = dup.enrollment_id
             AND k.fee_category_id = fv.fee_category_id
            WHERE dup.id <> k.keep_id
            """
        )
    ).rowcount

    bind.execute(text("DROP TEMPORARY TABLE IF EXISTS _ef_kept"))

    if retirees:
        logger.warning(
            "Frais d'eleves en double fusionnes par categorie : %s ligne(s) supprimee(s), "
            "%s de dette retiree, %s allocation(s) de versement repointee(s). "
            "Verifier a la caisse les inscriptions dont le total impute depasse "
            "desormais le montant du frais.",
            retirees,
            mesure.dette,
            deplacees,
        )


def upgrade() -> None:
    bind = op.get_bind()

    _merge_duplicates(bind)

    if not _has_column(bind):
        op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN {_COLUMN} BIGINT NULL AFTER fee_variant_id")

    bind.execute(
        text(
            f"""
            UPDATE {_TABLE} ef
            JOIN fee_variants fv ON fv.id = ef.fee_variant_id
            SET ef.{_COLUMN} = fv.fee_category_id
            WHERE ef.{_COLUMN} IS NULL OR ef.{_COLUMN} <> fv.fee_category_id
            """
        )
    )

    op.execute(f"ALTER TABLE {_TABLE} MODIFY COLUMN {_COLUMN} BIGINT NOT NULL")

    if not _has_index(bind):
        op.create_unique_constraint(_INDEX, _TABLE, ["enrollment_id", _COLUMN])

    if not _has_fk(bind):
        op.create_foreign_key(_FK, _TABLE, "fee_categories", [_COLUMN], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    """On retire l'invariant, pas la fusion.

    Ressusciter les lignes supprimees redoublerait la dette des familles
    concernees : elles n'ont jamais ete dues deux fois.
    """
    bind = op.get_bind()

    if _has_fk(bind):
        op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    if _has_index(bind):
        op.drop_constraint(_INDEX, _TABLE, type_="unique")
    if _has_column(bind):
        op.drop_column(_TABLE, _COLUMN)
