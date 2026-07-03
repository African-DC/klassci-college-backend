"""Service des pièces jointes élève : catalogue de types + documents téléversés."""

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.attachment import DocumentType, StudentDocument
from app.models.user import Student


async def list_document_types(db: AsyncSession) -> list[DocumentType]:
    rows = (await db.execute(select(DocumentType).order_by(DocumentType.name))).scalars().all()
    return list(rows)


async def _ensure_type(db: AsyncSession, name: str) -> None:
    """Ajoute le type au catalogue s'il n'existe pas (création à la volée)."""
    name = name.strip()
    if not name:
        return
    exists = (
        await db.execute(select(DocumentType).where(DocumentType.name == name))
    ).scalar_one_or_none()
    if exists is None:
        db.add(DocumentType(name=name))
        await db.flush()


async def list_student_documents(db: AsyncSession, student_id: int) -> list[StudentDocument]:
    stmt = (
        select(StudentDocument)
        .where(StudentDocument.student_id == student_id)
        .order_by(StudentDocument.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def add_student_document(
    db: AsyncSession,
    student_id: int,
    *,
    document_type: str,
    file_url: str,
    file_name: str | None,
    mime_type: str | None,
    uploaded_by: int,
) -> StudentDocument:
    student = (
        await db.execute(select(Student).where(Student.id == student_id))
    ).scalar_one_or_none()
    if student is None:
        raise NotFoundError("Student", student_id)

    label = document_type.strip() or "Autre"
    doc = StudentDocument(
        student_id=student_id,
        document_type=label,
        file_url=file_url,
        file_name=file_name,
        mime_type=mime_type,
        uploaded_by=uploaded_by,
    )
    db.add(doc)
    await _ensure_type(db, label)
    await db.flush()
    doc_id = doc.id
    await db.commit()
    return (
        await db.execute(select(StudentDocument).where(StudentDocument.id == doc_id))
    ).scalar_one()


async def delete_student_document(db: AsyncSession, student_id: int, doc_id: int) -> None:
    doc = (
        await db.execute(
            select(StudentDocument).where(
                StudentDocument.id == doc_id, StudentDocument.student_id == student_id
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        raise NotFoundError("Document", doc_id)
    await db.execute(sa_delete(StudentDocument).where(StudentDocument.id == doc_id))
    await db.commit()
