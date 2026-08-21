"""Les écrans de bord qui resteraient vides sans un peu de matière.

Congés, cloche de notifications, pièces jointes, corbeille, promotions : cinq
fonctions périphériques que personne ne pense à montrer, et qui décident
pourtant de l'impression laissée par une démonstration. Un écran vide se lit
comme un écran cassé.

Chaque étape est isolée derrière son propre garde. Aucune n'est indispensable
au reste du semis, et il serait absurde qu'une pièce jointe impossible à écrire
sur le disque fasse échouer une base de six cents élèves.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.cli.seed_demo.context import SeedContext, logger
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import Payment
from app.models.grade import Grade
from app.models.leave import LeaveRequest, LeaveType
from app.models.notification import Notification, NotificationType
from app.models.user import StaffProfile, Student, TeacherProfile, User, UserRoleEnum
from app.schemas.leave import LeaveRequestCreate
from app.services import (
    admin_service,
    archive_service,
    attachment_service,
    leave_service,
    notification_dispatch_service,
    promotion_service,
)

LEAVE_COUNT = 14
NOTIFICATION_COUNT = 30
DOCUMENT_STUDENTS = 40
ARCHIVE_COUNT = 4

#: Répertoire servi par l'application sous `/uploads`. Écrire les pièces
#: jointes ailleurs donnerait des liens morts dans la fiche élève.
UPLOAD_ROOT = Path("/tmp/klassci-uploads/justificatifs")

_LEAVES: tuple[tuple[str, int, str], ...] = (
    (LeaveType.SICK.value, 3, "Arrêt maladie, certificat médical transmis au secrétariat"),
    (LeaveType.ANNUAL.value, 7, "Congé annuel, période creuse après les compositions"),
    (LeaveType.EXCEPTIONAL.value, 2, "Décès d'un proche, obsèques au village"),
    (LeaveType.TRAINING.value, 4, "Séminaire DRENA sur l'approche par les compétences"),
    (LeaveType.MATERNITY.value, 45, "Congé de maternité, dates confirmées par la CNPS"),
    (LeaveType.OTHER.value, 1, "Convocation administrative à la DRENA"),
)

_APPROVALS: tuple[str, ...] = (
    "Accordé, remplacement assuré par l'équipe de la discipline.",
    "Accordé, reprise attendue le lundi suivant.",
    "Accordé au vu des pièces justificatives.",
)

_REJECTIONS: tuple[str, ...] = (
    "Refusé : période de compositions, aucun remplaçant disponible.",
    "Refusé en l'état, à représenter avec les pièces justificatives.",
)

#: Ce que la cloche annonce vraiment à chaque famille et à chaque enseignant.
_NOTICES: tuple[tuple[NotificationType, str, str], ...] = (
    (
        NotificationType.PAYMENT_DUE,
        "Échéance de scolarité",
        "La deuxième tranche de scolarité arrive à échéance à la fin du mois.",
    ),
    (
        NotificationType.PAYMENT_RECEIVED,
        "Versement enregistré",
        "Votre versement a bien été enregistré à la caisse, le reçu est disponible.",
    ),
    (
        NotificationType.BULLETIN_PUBLISHED,
        "Bulletin disponible",
        "Le bulletin du trimestre est consultable depuis votre espace.",
    ),
    (
        NotificationType.GRADE_AVAILABLE,
        "Nouvelle note saisie",
        "Une note de composition vient d'être publiée par l'enseignant.",
    ),
    (
        NotificationType.ABSENCE_RECORDED,
        "Absence signalée",
        "Une absence a été relevée en cours ce matin, merci de la justifier.",
    ),
    (
        NotificationType.SYSTEM,
        "Réunion de rentrée",
        "La réunion des parents d'élèves se tiendra samedi à neuf heures.",
    ),
)

#: Pièces réellement exigées au dossier d'inscription d'un collège ivoirien.
_DOCUMENT_TYPES: tuple[str, ...] = (
    "Extrait de naissance",
    "Certificat de scolarité de l'année précédente",
    "Photo d'identité",
    "Fiche d'affectation",
    "Bulletin de l'année précédente",
    "Copie de la CNI du tuteur",
)


def _minimal_pdf(title: str) -> bytes:
    """Un PDF d'une page, valide, pour que le lien de la pièce jointe ouvre.

    Un lien qui renvoie une erreur 404 est pire qu'une fiche sans pièce jointe :
    le visiteur conclut que le téléversement est cassé.
    """
    stream = f"BT /F1 14 Tf 60 760 Td ({title}) Tj ET".encode("latin-1", "replace")
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    start, size = len(out), len(bodies) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, start)
    return bytes(out)


async def ensure_leave_requests(ctx: SeedContext) -> None:
    """Des demandes de congé posées par l'équipe, la plupart déjà tranchées.

    Quatre restent en attente : c'est la file que le directeur ouvre le matin,
    et un écran sans file d'attente ne montre pas à quoi sert l'écran.
    """
    teachers = (await ctx.db.execute(select(TeacherProfile.user_id))).scalars().all()
    staff = (await ctx.db.execute(select(StaffProfile.user_id))).scalars().all()
    authors = [*sorted(teachers)[:10], *sorted(staff)[:4]]
    if not authors:
        return

    posted = (await ctx.db.execute(select(LeaveRequest))).scalars().all()
    existing = {(row.user_id, row.leave_type, row.start_date) for row in posted}
    reviewer = ctx.staff_user_by_role.get("director") or ctx.actor_id

    for index in range(min(LEAVE_COUNT, len(authors))):
        user_id = authors[index]
        leave_type, span, reason = _LEAVES[index % len(_LEAVES)]
        start = ctx.today - timedelta(days=90 - index * 6)
        if (user_id, leave_type, start) in existing:
            continue
        try:
            created = await leave_service.create_request(
                ctx.db,
                user_id,
                LeaveRequestCreate(
                    leave_type=leave_type,
                    start_date=start,
                    end_date=start + timedelta(days=span),
                    reason=reason,
                ),
            )
            ctx.tally("demandes de congé")
            # Les quatre dernières restent ouvertes.
            if index < LEAVE_COUNT - 4:
                approve = index % 4 != 3
                wording = _APPROVALS if approve else _REJECTIONS
                await leave_service.review_request(
                    ctx.db,
                    created["id"],
                    reviewer_id=reviewer,
                    approve=approve,
                    comment=wording[index % len(wording)],
                )
                ctx.tally("congés traités")
        except Exception as error:  # noqa: BLE001
            await ctx.db.rollback()
            logger.warning("Demande de congé non posée pour l'agent %s : %s", user_id, error)


async def _users_of(ctx: SeedContext, role: UserRoleEnum, limit: int) -> list[int]:
    stmt = select(User.id).where(User.role == role).order_by(User.id).limit(limit)
    return list((await ctx.db.execute(stmt)).scalars().all())


async def ensure_notifications(ctx: SeedContext) -> None:
    """De quoi remplir la cloche des trois portails, moitié lue, moitié non.

    Le service pose la notification sans valider : la transaction est refermée
    ici, ligne par ligne, sinon rien de tout cela n'existerait après la
    déconnexion et une seule ligne refusée emporterait les vingt-neuf autres.
    """
    audience: list[int] = []
    for role in (UserRoleEnum.PARENT, UserRoleEnum.TEACHER, UserRoleEnum.STUDENT):
        audience.extend(await _users_of(ctx, role, NOTIFICATION_COUNT // 3 + 2))
    if not audience:
        return

    posted = (await ctx.db.execute(select(Notification))).scalars().all()
    existing = {(row.user_id, row.type, row.title) for row in posted}
    # Le quota est un total : la cloche se remplit une fois, pas trente lignes
    # de plus à chaque relance.
    titles = {title for _kind, title, _body in _NOTICES}
    if sum(1 for row in posted if row.title in titles) >= NOTIFICATION_COUNT:
        return
    written = 0
    for index in range(NOTIFICATION_COUNT):
        user_id = audience[index % len(audience)]
        kind, title, body = _NOTICES[index % len(_NOTICES)]
        if (user_id, kind.value, title) in existing:
            continue
        try:
            notice = await notification_dispatch_service.dispatch_notification(
                ctx.db, user_id, kind, {"title": title, "body": body}
            )
            # Une cloche entièrement non lue ferait croire à un compte jamais
            # ouvert ; une cloche toute lue ne montrerait pas la pastille.
            if index % 2 == 0:
                notice.read = True
                notice.read_at = datetime.utcnow()
            await ctx.db.commit()
            written += 1
        except Exception as error:  # noqa: BLE001
            await ctx.db.rollback()
            logger.warning("Notification non posée pour l'utilisateur %s : %s", user_id, error)

    ctx.tally("notifications", written)


async def ensure_student_documents(ctx: SeedContext) -> None:
    """Deux ou trois pièces au dossier de quarante élèves.

    Les mêmes fichiers servent à tous : ce sont les liens qu'on vient vérifier
    dans la fiche élève, pas leur contenu, et écrire cent PDF n'apprendrait
    rien de plus au visiteur.
    """
    try:
        UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        for label in _DOCUMENT_TYPES[:3]:
            target = UPLOAD_ROOT / f"{label.split()[0].lower()}.pdf"
            if not target.exists():
                target.write_bytes(_minimal_pdf(label))
    except OSError as error:
        logger.warning("Pièces jointes ignorées, écriture impossible : %s", error)
        return

    stmt = select(Student.id).join(Enrollment, Enrollment.student_id == Student.id)
    stmt = stmt.where(Enrollment.academic_year_id == ctx.academic_year_id).order_by(Student.id)
    students = list((await ctx.db.execute(stmt.limit(DOCUMENT_STUDENTS))).scalars().all())
    uploader = ctx.staff_user_by_role.get("staff") or ctx.actor_id
    files = sorted(path.name for path in UPLOAD_ROOT.glob("*.pdf"))

    for index, student_id in enumerate(students):
        documents = await attachment_service.list_student_documents(ctx.db, student_id)
        held = {doc.document_type for doc in documents}
        for offset in range(2 + index % 2):
            label = _DOCUMENT_TYPES[(index + offset) % len(_DOCUMENT_TYPES)]
            if label in held:
                continue
            name = files[(index + offset) % len(files)]
            try:
                await attachment_service.add_student_document(
                    ctx.db,
                    student_id,
                    document_type=label,
                    file_url=f"/uploads/justificatifs/{name}",
                    file_name=f"{label}.pdf",
                    mime_type="application/pdf",
                    uploaded_by=uploader,
                )
                ctx.tally("pièces jointes")
            except Exception as error:  # noqa: BLE001
                await ctx.db.rollback()
                logger.warning("Pièce jointe refusée sur l'élève %s : %s", student_id, error)


async def ensure_recycle_bin(ctx: SeedContext) -> None:
    """Quatre fiches à la corbeille, choisies pour n'emporter aucune trace.

    Uniquement des dossiers restés à l'état de demande, sans versement ni note :
    archiver un élève qui a payé masquerait sa ligne dans les écrans financiers
    d'une base de démonstration, ce qui se remarque tout de suite.
    """
    stmt = (
        select(Student.id)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(
            Enrollment.status == EnrollmentStatus.PROSPECT,
            Student.archived_at.is_(None),
            ~select(Grade.id).where(Grade.student_id == Student.id).exists(),
            ~select(Payment.id).where(Payment.enrollment_id == Enrollment.id).exists(),
        )
        .order_by(Student.id)
        .limit(ARCHIVE_COUNT)
    )
    # Quatre fiches à la corbeille, au total. Le filtre écarte les fiches déjà
    # archivées : sans cette borne, chaque relance en archiverait quatre
    # nouvelles et la corbeille grossirait sans fin.
    already = int(
        (
            await ctx.db.execute(
                select(func.count()).select_from(Student).where(Student.archived_at.is_not(None))
            )
        ).scalar_one()
    )
    if already >= ARCHIVE_COUNT:
        return

    reason = "Dossier de pré-inscription jamais confirmé par la famille"
    for student_id in (await ctx.db.execute(stmt)).scalars().all()[: ARCHIVE_COUNT - already]:
        try:
            await archive_service.archive_record(
                ctx.db,
                admin_service.STUDENT_KIND,
                student_id,
                reason=reason,
                actor_id=ctx.actor_id,
            )
            ctx.tally("fiches archivées")
        except Exception as error:  # noqa: BLE001 : déjà archivée, ou courriel muet
            await ctx.db.rollback()
            logger.info("Fiche élève %s non archivée : %s", student_id, error)


async def ensure_promotion(ctx: SeedContext) -> None:
    """Une seule classe promue vers l'année suivante, pour montrer l'écran.

    Une seule : promouvoir l'école entière remplirait l'année suivante de six
    cents inscriptions qu'aucune démonstration ne regarde, et le passage de
    classe se raconte aussi bien sur une division que sur dix-huit.
    """
    if ctx.next_year_id is None:
        logger.info("Pas d'année suivante ouverte : promotion non exécutée.")
        return

    source = ctx.class_ids.get(("6ème", None, "A"))
    target = ctx.class_ids.get(("5ème", None, "A"))
    if source is None or target is None:
        logger.info("Classes 6e A ou 5e A absentes : promotion non exécutée.")
        return

    try:
        result = await promotion_service.execute_promotion(
            ctx.db,
            source_ay_id=ctx.academic_year_id,
            target_ay_id=ctx.next_year_id,
            class_mapping={source: target},
            executed_by=ctx.actor_id,
        )
    except Exception as error:  # noqa: BLE001
        await ctx.db.rollback()
        logger.warning("Promotion de la 6e A non exécutée : %s", error)
        return

    # Le service saute les élèves déjà inscrits l'année cible : relancer le
    # semis ne promeut personne deux fois.
    ctx.tally("élèves promus", result.promoted_count)


async def run(ctx: SeedContext) -> None:
    await ensure_leave_requests(ctx)
    await ensure_notifications(ctx)
    await ensure_student_documents(ctx)
    await ensure_recycle_bin(ctx)
    await ensure_promotion(ctx)
