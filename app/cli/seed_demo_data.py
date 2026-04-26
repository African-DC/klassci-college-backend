"""CLI — Seed demo data for a tenant.

Usage:
    python -m app.cli.seed_demo_data --tenant local
"""

import argparse
import asyncio
import logging
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cote d'Ivoire school system data
# ---------------------------------------------------------------------------

LEVELS = [
    {"name": "6eme", "order": 1},
    {"name": "5eme", "order": 2},
    {"name": "4eme", "order": 3},
    {"name": "3eme", "order": 4},
    {"name": "2nde", "order": 5},
    {"name": "1ere", "order": 6},
    {"name": "Terminale", "order": 7},
]

# Series (lycee only — levels 5-7):
SERIES = [
    {"name": "A", "level_order": 5},  # 2nde
    {"name": "C", "level_order": 6},  # 1ere
    {"name": "D", "level_order": 6},  # 1ere
    {"name": "A", "level_order": 7},  # Terminale
    {"name": "C", "level_order": 7},  # Terminale
    {"name": "D", "level_order": 7},  # Terminale
]

SUBJECTS = [
    {"name": "Mathematiques", "coefficient": 4, "hours_per_week": 5},
    {"name": "Francais", "coefficient": 4, "hours_per_week": 5},
    {"name": "Anglais", "coefficient": 2, "hours_per_week": 3},
    {"name": "Sciences Physiques", "coefficient": 3, "hours_per_week": 4},
    {"name": "Sciences de la Vie et de la Terre", "coefficient": 2, "hours_per_week": 3},
    {"name": "Histoire-Geographie", "coefficient": 2, "hours_per_week": 3},
    {"name": "Education Civique et Morale", "coefficient": 1, "hours_per_week": 1},
    {"name": "Education Physique et Sportive", "coefficient": 1, "hours_per_week": 2},
    {"name": "Dessin / Arts Plastiques", "coefficient": 1, "hours_per_week": 1},
    {"name": "Musique", "coefficient": 1, "hours_per_week": 1},
    {"name": "Philosophie", "coefficient": 3, "hours_per_week": 4},
    {"name": "Espagnol", "coefficient": 2, "hours_per_week": 2},
    {"name": "Allemand", "coefficient": 2, "hours_per_week": 2},
    {"name": "Informatique", "coefficient": 1, "hours_per_week": 1},
]

FEE_CATEGORIES = [
    {"name": "Inscription", "description": "Frais d'inscription annuels"},
    {"name": "Scolarite Trimestre 1", "description": "Frais de scolarite 1er trimestre"},
    {"name": "Scolarite Trimestre 2", "description": "Frais de scolarite 2eme trimestre"},
    {"name": "Scolarite Trimestre 3", "description": "Frais de scolarite 3eme trimestre"},
    {"name": "COGES", "description": "Contribution au comite de gestion"},
    {"name": "Tenue scolaire", "description": "Frais de tenue obligatoire"},
]

# 2 classes per level: A and B
CLASS_SUFFIXES = ["A", "B"]

# Demo teacher
DEMO_TEACHER = {
    "first_name": "Marie",
    "last_name": "Kone",
    "speciality": "Mathematiques",
    "email": "marie.kone@demo.ci",
    "password_hash": "$2b$12$demohashedpasswordnotreal000000000000000000000000",
}


async def seed_demo_data(tenant_slug: str) -> None:
    """Insert demo data into the tenant database."""
    from app.core.config import settings

    tenant_url = settings.DATABASE_URL.format(tenant=tenant_slug)
    engine = create_async_engine(tenant_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with factory() as db:
            async with db.begin():
                counts: dict[str, int] = {}

                # 1. Academic year
                await db.execute(
                    text(
                        "INSERT IGNORE INTO academic_years (name, start_date, end_date, is_current) "
                        "VALUES (:name, :start, :end, :current)"
                    ),
                    {
                        "name": "2025-2026",
                        "start": "2025-09-08",
                        "end": "2026-06-30",
                        "current": True,
                    },
                )
                ay_row = await db.execute(
                    text("SELECT id FROM academic_years WHERE name = '2025-2026'")
                )
                academic_year_id = ay_row.scalar_one()
                counts["academic_years"] = 1

                # 2. Levels
                for lvl in LEVELS:
                    await db.execute(
                        text("INSERT IGNORE INTO levels (name, `order`) VALUES (:name, :ord)"),
                        {"name": lvl["name"], "ord": lvl["order"]},
                    )
                counts["levels"] = len(LEVELS)

                # 3. Series (lycee only)
                for s in SERIES:
                    level_row = await db.execute(
                        text("SELECT id FROM levels WHERE `order` = :ord"),
                        {"ord": s["level_order"]},
                    )
                    level_id = level_row.scalar_one()
                    await db.execute(
                        text(
                            "INSERT IGNORE INTO series (level_id, name) VALUES (:level_id, :name)"
                        ),
                        {"level_id": level_id, "name": s["name"]},
                    )
                counts["series"] = len(SERIES)

                # 4. Classes (2 per level)
                class_count = 0
                for lvl in LEVELS:
                    level_row = await db.execute(
                        text("SELECT id FROM levels WHERE name = :name"),
                        {"name": lvl["name"]},
                    )
                    level_id = level_row.scalar_one()

                    for suffix in CLASS_SUFFIXES:
                        class_name = f"{lvl['name']} {suffix}"
                        await db.execute(
                            text(
                                "INSERT IGNORE INTO classes "
                                "(name, level_id, academic_year_id, max_students) "
                                "VALUES (:name, :level_id, :ay_id, :max)"
                            ),
                            {
                                "name": class_name,
                                "level_id": level_id,
                                "ay_id": academic_year_id,
                                "max": 50,
                            },
                        )
                        class_count += 1
                counts["classes"] = class_count

                # 5. Subjects
                for subj in SUBJECTS:
                    await db.execute(
                        text(
                            "INSERT IGNORE INTO subjects "
                            "(name, coefficient, hours_per_week) "
                            "VALUES (:name, :coeff, :hours)"
                        ),
                        {
                            "name": subj["name"],
                            "coeff": subj["coefficient"],
                            "hours": subj["hours_per_week"],
                        },
                    )
                counts["subjects"] = len(SUBJECTS)

                # 6. Fee categories
                for fc in FEE_CATEGORIES:
                    await db.execute(
                        text(
                            "INSERT IGNORE INTO fee_categories (name, description) "
                            "VALUES (:name, :desc)"
                        ),
                        {"name": fc["name"], "desc": fc["description"]},
                    )
                counts["fee_categories"] = len(FEE_CATEGORIES)

                # 7. Demo teacher (user + teacher_profile)
                await db.execute(
                    text(
                        "INSERT IGNORE INTO users (email, hashed_password, role, is_active) "
                        "VALUES (:email, :pwd, 'teacher', 1)"
                    ),
                    {
                        "email": DEMO_TEACHER["email"],
                        "pwd": DEMO_TEACHER["password_hash"],
                    },
                )
                teacher_row = await db.execute(
                    text("SELECT id FROM users WHERE email = :email"),
                    {"email": DEMO_TEACHER["email"]},
                )
                teacher_user_id = teacher_row.scalar_one()

                await db.execute(
                    text(
                        "INSERT IGNORE INTO teacher_profiles "
                        "(user_id, first_name, last_name, speciality) "
                        "VALUES (:uid, :fn, :ln, :spec)"
                    ),
                    {
                        "uid": teacher_user_id,
                        "fn": DEMO_TEACHER["first_name"],
                        "ln": DEMO_TEACHER["last_name"],
                        "spec": DEMO_TEACHER["speciality"],
                    },
                )
                counts["teachers"] = 1

        # Print summary
        print(f"\nDemo data seeded for tenant '{tenant_slug}':")
        for entity, count in counts.items():
            print(f"   {entity:20s} : {count}")
        print()

    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data for a KLASSCI tenant")
    parser.add_argument("--tenant", required=True, help="Tenant slug (database name)")
    args = parser.parse_args()

    try:
        asyncio.run(seed_demo_data(args.tenant))
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
