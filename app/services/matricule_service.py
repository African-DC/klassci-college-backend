"""Generate enrollment numbers from configurable patterns."""

import re

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import AcademicYear, SchoolSettings


async def generate_enrollment_number(
    db: AsyncSession,
    school_settings: SchoolSettings,
    *,
    class_data: object | None = None,
) -> str | None:
    """Generate an enrollment number from the configured pattern.

    Supported tokens:
    - {YEAR}       : start year of current academic year (e.g. 2026)
    - {YEAR_SHORT} : last 2 digits (e.g. 26)
    - {YEAR_RANGE} : full academic year name (e.g. 2025-2026)
    - {SEQ}        : auto-increment sequence (raw)
    - {SEQ:04}     : zero-padded to 4 digits
    - {SEQ:06}     : zero-padded to 6 digits
    - {SCHOOL}     : ministry_code or first 3 chars of school_name
    - {LEVEL}      : level name if class provided
    - {CLASS}      : class name if provided

    Returns None if no pattern is configured (manual entry required).
    """
    pattern = school_settings.enrollment_number_pattern
    if not pattern:
        return None

    # Increment counter atomically via raw SQL to avoid race conditions
    await db.execute(
        text(
            "UPDATE school_settings "
            "SET enrollment_number_counter = enrollment_number_counter + 1 "
            "WHERE id = :id"
        ),
        {"id": school_settings.id},
    )
    await db.flush()

    result_row = await db.execute(
        text("SELECT enrollment_number_counter FROM school_settings WHERE id = :id"),
        {"id": school_settings.id},
    )
    counter = result_row.scalar()

    # Get current academic year
    stmt = select(AcademicYear).where(AcademicYear.is_current == True)  # noqa: E712
    year_result = await db.execute(stmt)
    current_year = year_result.scalar_one_or_none()
    year_name = current_year.name if current_year else "0000"
    year_start = year_name.split("-")[0] if "-" in year_name else year_name

    # Build school identifier
    school_code = (
        school_settings.ministry_code
        or (school_settings.school_name[:3] if school_settings.school_name else "XXX")
    ).upper()

    # Replace tokens
    output = pattern
    output = output.replace("{YEAR}", year_start)
    output = output.replace("{YEAR_SHORT}", year_start[-2:])
    output = output.replace("{YEAR_RANGE}", year_name)
    output = output.replace("{SCHOOL}", school_code)

    if class_data:
        output = output.replace("{LEVEL}", str(getattr(class_data, "level_name", "")))
        output = output.replace("{CLASS}", str(getattr(class_data, "name", "")))
    else:
        output = output.replace("{LEVEL}", "")
        output = output.replace("{CLASS}", "")

    # Handle {SEQ:N} pattern (zero-padded)
    seq_match = re.search(r"\{SEQ:(\d+)\}", output)
    if seq_match:
        padding = int(seq_match.group(1))
        output = output.replace(seq_match.group(0), str(counter).zfill(padding))
    else:
        output = output.replace("{SEQ}", str(counter))

    return output


async def preview_enrollment_number(
    db: AsyncSession,
    pattern: str,
) -> dict:
    """Preview what an enrollment number would look like without incrementing the counter.

    Returns the preview string and the next sequence number.
    """
    # Get school settings for context
    stmt = select(SchoolSettings).limit(1)
    result = await db.execute(stmt)
    school = result.scalar_one_or_none()

    counter = (school.enrollment_number_counter + 1) if school else 1

    # Get current academic year
    year_stmt = select(AcademicYear).where(AcademicYear.is_current == True)  # noqa: E712
    year_result = await db.execute(year_stmt)
    current_year = year_result.scalar_one_or_none()
    year_name = current_year.name if current_year else "0000"
    year_start = year_name.split("-")[0] if "-" in year_name else year_name

    school_code = ""
    if school:
        school_code = (
            school.ministry_code or (school.school_name[:3] if school.school_name else "XXX")
        ).upper()
    else:
        school_code = "XXX"

    output = pattern
    output = output.replace("{YEAR}", year_start)
    output = output.replace("{YEAR_SHORT}", year_start[-2:])
    output = output.replace("{YEAR_RANGE}", year_name)
    output = output.replace("{SCHOOL}", school_code)
    output = output.replace("{LEVEL}", "6EME")
    output = output.replace("{CLASS}", "6A")

    seq_match = re.search(r"\{SEQ:(\d+)\}", output)
    if seq_match:
        padding = int(seq_match.group(1))
        output = output.replace(seq_match.group(0), str(counter).zfill(padding))
    else:
        output = output.replace("{SEQ}", str(counter))

    return {
        "pattern": pattern,
        "preview": output,
        "next_sequence": counter,
    }
