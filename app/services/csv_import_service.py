"""Service d'import CSV — import en batch d'élèves depuis un fichier CSV."""

import csv
import io
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError
from app.models.academic import AcademicYear, Class, SchoolSettings
from app.models.user import Student
from app.services.matricule_service import generate_enrollment_number

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "first_name",
    "last_name",
    "birth_date",
    "genre",
    "enrollment_number",
    "class_name",
}

# `birth_place` figure dans le modèle mais volontairement PAS dans
# REQUIRED_COLUMNS : les fichiers déjà constitués par les écoles ne le portent
# pas, et rejeter un import de rentrée entier pour une colonne facultative
# serait disproportionné. Colonne absente ou vide == lieu de naissance inconnu.
CSV_TEMPLATE = (
    "first_name,last_name,birth_date,birth_place,genre,enrollment_number,class_name\n"
    "Jean,Dupont,2010-05-15,Abidjan,M,MAT001,6eme A\n"
    "Marie,Koné,2011-03-22,Bouaké,F,,6eme B\n"
)


def _parse_birth_date(value: str) -> date | None:
    """Parse une date au format YYYY-MM-DD ou DD/MM/YYYY."""
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _validate_row(row: dict[str, str], row_num: int) -> tuple[dict | None, str | None]:
    """Valide une ligne CSV et retourne les données nettoyées ou une erreur."""
    first_name = row.get("first_name", "").strip()
    last_name = row.get("last_name", "").strip()

    if not first_name or not last_name:
        return None, f"Row {row_num}: first_name and last_name are required"

    genre = row.get("genre", "").strip().upper()
    if genre and genre not in ("M", "F"):
        return None, f"Row {row_num}: genre must be 'M' or 'F', got '{genre}'"

    birth_date_str = row.get("birth_date", "").strip()
    birth_date = _parse_birth_date(birth_date_str)
    if birth_date_str and birth_date is None:
        return (
            None,
            f"Row {row_num}: invalid birth_date format '{birth_date_str}' (expected YYYY-MM-DD or DD/MM/YYYY)",
        )

    class_name = row.get("class_name", "").strip()
    if not class_name:
        return None, f"Row {row_num}: class_name is required"

    enrollment_number = row.get("enrollment_number", "").strip() or None
    birth_place = row.get("birth_place", "").strip() or None

    return {
        "first_name": first_name,
        "last_name": last_name,
        "birth_date": birth_date,
        "birth_place": birth_place,
        "genre": genre or None,
        "enrollment_number": enrollment_number,
        "class_name": class_name,
    }, None


async def import_students_from_csv(
    db: AsyncSession,
    csv_bytes: bytes,
    *,
    imported_by: int,
) -> dict:
    """Parse et importe les élèves depuis un CSV.

    Retourne un rapport : {imported: int, errors: list[str], skipped: int}.
    """
    try:
        content = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = csv_bytes.decode("latin-1")
        except UnicodeDecodeError as err:
            raise BusinessValidationError("Unable to decode CSV file. Use UTF-8 encoding.") from err

    reader = csv.DictReader(io.StringIO(content))

    if reader.fieldnames is None:
        raise BusinessValidationError("CSV file is empty or has no header row")

    actual_columns = {col.strip().lower() for col in reader.fieldnames}
    missing = REQUIRED_COLUMNS - actual_columns
    if missing:
        raise BusinessValidationError(f"Missing CSV columns: {', '.join(sorted(missing))}")

    # Normalize fieldnames
    reader.fieldnames = [col.strip().lower() for col in reader.fieldnames]

    # Pre-fetch current academic year
    stmt = select(AcademicYear).where(AcademicYear.is_current == True)  # noqa: E712
    result = await db.execute(stmt)
    current_year = result.scalar_one_or_none()
    if not current_year:
        raise BusinessValidationError("No current academic year configured")

    # Pre-fetch school settings for auto-matricule
    settings_result = await db.execute(select(SchoolSettings).limit(1))
    school_settings = settings_result.scalar_one_or_none()

    # Pre-fetch classes (Class est universel post-refactor #97 : pas de filtre AY)
    stmt = select(Class)
    result = await db.execute(stmt)
    classes = {c.name.strip().lower(): c for c in result.scalars().all()}

    # Pre-fetch existing enrollment numbers to detect duplicates
    stmt = select(Student.enrollment_number).where(Student.enrollment_number.isnot(None))
    result = await db.execute(stmt)
    existing_numbers = {r[0] for r in result.all()}

    imported = 0
    skipped = 0
    errors: list[str] = []

    rows: list[tuple[int, dict[str, str]]] = []
    for row_num, row in enumerate(reader, start=2):
        rows.append((row_num, row))

    if not rows:
        raise BusinessValidationError("CSV file contains no data rows")

    for row_num, row in rows:
        data, error = _validate_row(row, row_num)
        if error:
            errors.append(error)
            continue

        class_key = data["class_name"].strip().lower()
        class_ = classes.get(class_key)
        if class_ is None:
            errors.append(
                f"Row {row_num}: class '{data['class_name']}' not found for current academic year"
            )
            continue

        # Check enrollment_number duplicate
        if data["enrollment_number"] and data["enrollment_number"] in existing_numbers:
            errors.append(
                f"Row {row_num}: enrollment_number '{data['enrollment_number']}' already exists"
            )
            skipped += 1
            continue

        try:
            async with db.begin_nested():
                student = Student(
                    first_name=data["first_name"],
                    last_name=data["last_name"],
                    birth_date=data["birth_date"],
                    birth_place=data["birth_place"],
                    genre=data["genre"],
                    enrollment_number=data["enrollment_number"],
                )
                db.add(student)
                await db.flush()

                # Auto-generate enrollment number if not provided
                if not data["enrollment_number"]:
                    if school_settings and school_settings.enrollment_number_pattern:
                        enrollment_num = await generate_enrollment_number(
                            db,
                            school_settings,
                            class_data=class_,
                        )
                        student.enrollment_number = enrollment_num
                        existing_numbers.add(enrollment_num)
                        await db.flush()

                if student.enrollment_number:
                    existing_numbers.add(student.enrollment_number)

                await audit_log(
                    db,
                    entity_type="student",
                    action=AuditAction.CREATE,
                    user_id=imported_by,
                    entity_id=student.id,
                    new_values={
                        "first_name": data["first_name"],
                        "last_name": data["last_name"],
                        "source": "csv_import",
                    },
                )

            imported += 1

        except Exception:
            logger.exception("Failed to import row %d", row_num)
            errors.append(f"Row {row_num}: unexpected error during import")
            continue

    if imported > 0:
        await db.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total_rows": len(rows),
    }
