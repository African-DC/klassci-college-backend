"""Prouve que la migration 0062 fusionne bien les frais en double par categorie.

La migration 0060 groupait sur `(enrollment_id, fee_variant_id)`. Le bug qu'elle
accompagnait produisait deux lignes de **variantes differentes** pour la meme
categorie : deux groupes, donc aucune fusion. Ce script construit exactement ce
cas sur une vraie base, execute le vrai SQL de la migration, et verifie qu'il
fusionne — puis annule tout.

Il verifie aussi la regle de conservation : on garde la ligne qui porte le plus
d'allocations, meme si ce n'est pas la plus ancienne, parce que c'est a elle que
l'argent est deja rattache.

    ../klassci-backend/venv/Scripts/python.exe scripts/verify_fee_category_merge.py

Le script doit tourner AVANT `alembic upgrade head` : une fois la contrainte
`uq_enrollment_fee_category` posee, la base refuse justement le doublon qu'il
faut construire pour eprouver la fusion. Il n'ecrit rien durablement : tout se
passe dans une transaction annulee a la fin, y compris sur une base qui porte
de vraies donnees.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

_RACINE = Path(__file__).resolve().parent.parent
_MIGRATION = _RACINE / "alembic" / "versions" / "20260821_0062_fee_category_uniqueness.py"

#: Identifiants hors de portee des donnees reelles : le script les cree et les
#: annule, il ne doit jamais toucher une ligne existante.
ANNEE = 900_000
INSCRIPTION = 900_001
VARIANTE_GENERALE = 900_010
VARIANTE_AFFECTEE = 900_011
FRAIS_ANCIEN = 900_020  # le plus ancien, une seule allocation
FRAIS_RECENT = 900_021  # le plus recent, deux allocations : c'est lui qu'on garde
VERSEMENT = 900_030


def _charge_migration():
    """Importe le module de migration sans passer par alembic."""
    spec = importlib.util.spec_from_file_location("migration_0062", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _url() -> str:
    """L'URL du locataire local, en pilote synchrone."""
    brut = os.environ.get("DATABASE_URL", "mysql+pymysql://root@localhost:3306/{tenant}").replace(
        "+aiomysql", "+pymysql"
    )
    return brut.replace("{tenant}", os.environ.get("TENANT_ID", "local"))


def _construit_le_cas(conn) -> None:
    """Une inscription, deux tarifs de la meme categorie, deux dettes."""
    eleve = conn.execute(text("SELECT id FROM students ORDER BY id LIMIT 1")).scalar_one_or_none()
    classe = conn.execute(text("SELECT id FROM classes ORDER BY id LIMIT 1")).scalar_one_or_none()
    categorie = conn.execute(
        text("SELECT id FROM fee_categories WHERE is_mandatory = 1 ORDER BY id LIMIT 1")
    ).scalar_one_or_none()
    if eleve is None or classe is None or categorie is None:
        raise SystemExit("Base trop vide : il faut un eleve, une classe et une categorie de frais.")

    # Une annee scolaire a nous : `uq_enrollment_student_year` interdit
    # d'inscrire deux fois le meme eleve sur la meme annee, et on ne veut
    # toucher a aucune inscription reelle.
    conn.execute(
        text(
            "INSERT INTO academic_years (id, name, start_date, end_date, is_current,"
            " created_at, updated_at)"
            " VALUES (:i, 'fusion-0062', '2999-09-01', '3000-07-31', 0, NOW(), NOW())"
        ),
        {"i": ANNEE},
    )
    conn.execute(
        text(
            "INSERT INTO enrollments (id, student_id, class_id, academic_year_id, status,"
            " created_at, updated_at)"
            " VALUES (:i, :s, :c, :a, 'valide', NOW(), NOW())"
        ),
        {"i": INSCRIPTION, "s": eleve, "c": classe, "a": ANNEE},
    )

    # Deux tarifs de la MEME categorie, distincts par leur portee : c'est
    # exactement ce que produit une ecole qui ajoute le tarif affecte
    # par-dessus sa grille generale.
    for variante, portee, montant in (
        (VARIANTE_GENERALE, None, "50000.00"),
        (VARIANTE_AFFECTEE, "affecte", "20000.00"),
    ):
        conn.execute(
            text(
                "INSERT INTO fee_variants (id, fee_category_id, academic_year_id, amount,"
                " assignment_scope, created_at, updated_at)"
                " VALUES (:i, :cat, :ay, :m, :p, NOW(), NOW())"
            ),
            {
                "i": variante,
                "cat": categorie,
                "ay": ANNEE,
                "m": montant,
                "p": portee,
            },
        )

    for frais, variante, montant in (
        (FRAIS_ANCIEN, VARIANTE_GENERALE, "50000.00"),
        (FRAIS_RECENT, VARIANTE_AFFECTEE, "20000.00"),
    ):
        conn.execute(
            text(
                "INSERT INTO enrollment_fees (id, enrollment_id, fee_variant_id, amount, status,"
                " created_at, updated_at)"
                " VALUES (:i, :e, :v, :m, 'pending', NOW(), NOW())"
            ),
            {"i": frais, "e": INSCRIPTION, "v": variante, "m": montant},
        )

    conn.execute(
        text(
            "INSERT INTO payments (id, enrollment_id, amount, method, status, created_at,"
            " updated_at)"
            " VALUES (:i, :e, '30000.00', 'cash', 'completed', NOW(), NOW())"
        ),
        {"i": VERSEMENT, "e": INSCRIPTION},
    )
    # La ligne recente porte deux allocations, l'ancienne une seule : c'est
    # elle qu'il faut garder, sinon l'argent change de contrepartie.
    for rang, (frais, montant) in enumerate(
        ((FRAIS_ANCIEN, "10000.00"), (FRAIS_RECENT, "10000.00"), (FRAIS_RECENT, "10000.00"))
    ):
        conn.execute(
            text(
                "INSERT INTO payment_allocations (id, payment_id, enrollment_fee_id, amount,"
                " created_at, updated_at)"
                " VALUES (:i, :p, :f, :m, NOW(), NOW())"
            ),
            {"i": 900_040 + rang, "p": VERSEMENT, "f": frais, "m": montant},
        )


def _lignes(conn) -> list[int]:
    return [
        r[0]
        for r in conn.execute(
            text("SELECT id FROM enrollment_fees WHERE enrollment_id = :e ORDER BY id"),
            {"e": INSCRIPTION},
        )
    ]


def _cibles_des_allocations(conn) -> list[int]:
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT enrollment_fee_id FROM payment_allocations WHERE payment_id = :p ORDER BY id"
            ),
            {"p": VERSEMENT},
        )
    ]


def main() -> int:
    # Le journal de la migration fait partie de la preuve : elle doit dire
    # combien de lignes elle fusionne et quelle dette elle retire.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    migration = _charge_migration()
    engine = create_engine(_url())

    with engine.begin() as conn:
        if conn.execute(text(_INDEX_QUERY)).scalar():
            print(
                "La contrainte uq_enrollment_fee_category est deja posee : la base refuse\n"
                "le doublon qu'il faut construire. Lancer `alembic downgrade -1` d'abord."
            )
            return 2

        _construit_le_cas(conn)
        avant = _lignes(conn)
        print(f"Avant : {len(avant)} lignes de frais pour la meme categorie -> {avant}")
        assert avant == [FRAIS_ANCIEN, FRAIS_RECENT], avant
        assert _cibles_des_allocations(conn) == [FRAIS_ANCIEN, FRAIS_RECENT, FRAIS_RECENT]

        migration._merge_duplicates(conn)

        apres = _lignes(conn)
        cibles = _cibles_des_allocations(conn)
        print(f"Apres : {len(apres)} ligne -> {apres}")
        print(f"Allocations repointees vers : {cibles}")

        assert apres == [FRAIS_RECENT], (
            "la ligne conservee doit etre celle qui porte le plus d'allocations, "
            f"pas la plus ancienne : {apres}"
        )
        assert cibles == [FRAIS_RECENT] * 3, cibles
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM payments WHERE id = :p"), {"p": VERSEMENT}
            ).scalar()
            == 1
        ), "le versement doit survivre a la fusion"

        conn.rollback()

    print("\nFusion prouvee : deux variantes d'une meme categorie ne font plus qu'une dette,")
    print("l'argent reste impute, et rien n'a ete ecrit durablement.")
    return 0


_INDEX_QUERY = (
    "SELECT COUNT(*) FROM information_schema.statistics "
    "WHERE table_schema = DATABASE() AND table_name = 'enrollment_fees' "
    "AND index_name = 'uq_enrollment_fee_category'"
)


if __name__ == "__main__":
    sys.exit(main())
