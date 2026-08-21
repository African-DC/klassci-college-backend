"""Les enseignants et le personnel des six métiers.

Le sexe et le type de contrat sont renseignés pour **chaque** enseignant, et ce
n'est pas un détail cosmétique : deux tableaux du rapport de fin de trimestre
de la DEEP restent vierges quand ils manquent, et l'inspection lit ce rapport.
Même chose pour le numéro CNPS et le numéro d'autorisation d'enseigner, que le
privé doit pouvoir présenter pour chacun de ses enseignants.
"""

from __future__ import annotations

import math

from sqlalchemy import select

from app.cli.seed_demo import names, plan
from app.cli.seed_demo.context import DEMO_PASSWORD, STAFF_DOMAIN, SeedContext
from app.models.user import StaffProfile, TeacherContract, TeacherProfile, User
from app.schemas.admin import StaffCreate, TeacherCreate
from app.services import admin_service

#: Heures hebdomadaires qu'un enseignant assure. Sert à dimensionner l'équipe :
#: en dessous, l'emploi du temps devient inconstructible ; au-dessus, un même
#: professeur se retrouve dans deux classes à la même heure.
WEEKLY_LOAD = 16

#: Répartition des contrats. Un privé ivoirien fonctionne majoritairement avec
#: des permanents, complétés par des vacataires, et quelques fonctionnaires
#: détachés de l'enseignement public.
CONTRACT_CYCLE: tuple[TeacherContract, ...] = (
    TeacherContract.PERMANENT,
    TeacherContract.PERMANENT,
    TeacherContract.VACATAIRE,
    TeacherContract.PERMANENT,
    TeacherContract.FONCTIONNAIRE,
    TeacherContract.VACATAIRE,
)

#: Les six métiers du secrétariat et de la direction, avec leur rôle d'accès.
#: `staff` est le slug historique du secrétariat : il porte des comptes en
#: production et vit dans les jetons déjà émis, on ne le renomme pas.
STAFF_ROLES: tuple[tuple[str, str, str], ...] = (
    ("staff", "Secrétaire principale", "F"),
    ("cashier", "Caissière", "F"),
    ("cashier", "Caissier", "M"),
    ("educator", "Éducateur", "M"),
    ("educator", "Éducatrice", "F"),
    ("accountant", "Comptable", "M"),
    ("studies_director", "Directeur des études", "M"),
    ("director", "Directeur général", "M"),
)


def _teacher_headcount() -> dict[str, int]:
    """Combien d'enseignants par matière, d'après les heures à couvrir.

    On additionne les heures de toutes les divisions ouvertes, puis on divise
    par le service d'un enseignant. C'est ce qui garantit qu'un emploi du temps
    sans chevauchement existe : à une matière par professeur pour dix-huit
    classes, aucun ordonnancement ne tient.
    """
    hours: dict[str, int] = {}
    for level, serie, _division in plan.class_plan():
        for name, _coefficient, weekly in plan.curriculum_for(level, serie):
            hours[name] = hours.get(name, 0) + weekly
    return {name: max(1, math.ceil(total / WEEKLY_LOAD)) for name, total in hours.items()}


def _identity_numbers(rng_seed: int) -> tuple[str, str]:
    """Numéro CNPS et numéro d'autorisation d'enseigner, tous deux réclamés."""
    return f"CNPS-{2_100_000 + rng_seed}", f"AUT-DRENA/{2020 + rng_seed % 6}/{rng_seed:04d}"


async def ensure_teachers(ctx: SeedContext) -> None:
    """Une équipe pédagogique dimensionnée sur les heures réellement à assurer."""
    existing_emails = set((await ctx.db.execute(select(User.email))).scalars().all())
    headcount = _teacher_headcount()

    rank = 0
    for subject in plan.all_subject_names():
        for index in range(headcount.get(subject, 1)):
            rank += 1
            genre = "F" if rank % 2 == 0 else "M"
            first_name, last_name = names.pick_full_name(ctx.rng, genre)
            # L'adresse tient au rang, pas au nom tiré : un ajustement du
            # répertoire de prénoms changerait sinon toutes les adresses, et la
            # relance créerait une seconde équipe pédagogique à côté de la
            # première.
            email = f"prof{rank:02d}@{STAFF_DOMAIN}"
            cnps, authorization = _identity_numbers(rank)
            contract = CONTRACT_CYCLE[rank % len(CONTRACT_CYCLE)]

            if email in existing_emails:
                teacher_id = await _teacher_id_for_email(ctx, email)
            else:
                response = await admin_service.create_teacher(
                    ctx.db,
                    TeacherCreate(
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        password=DEMO_PASSWORD,
                        speciality=subject,
                        phone=names.phone_number(ctx.rng),
                        genre=genre,
                        contract_type=contract,
                    ),
                    created_by=ctx.actor_id,
                )
                teacher_id = response.id
                ctx.tally("enseignants")

            await _complete_teacher_file(ctx, teacher_id, cnps, authorization, genre, contract)
            ctx.teachers_by_subject.setdefault(subject, []).append(teacher_id)
            _ = index

    await _complete_pre_existing_teachers(ctx)
    await ctx.db.commit()


async def _teacher_id_for_email(ctx: SeedContext, email: str) -> int:
    """L'identifiant du profil enseignant derrière une adresse déjà prise."""
    stmt = (
        select(TeacherProfile.id)
        .join(User, User.id == TeacherProfile.user_id)
        .where(User.email == email)
    )
    found = (await ctx.db.execute(stmt)).scalar_one_or_none()
    if found is None:
        raise RuntimeError(f"Compte {email} présent sans profil enseignant : semis interrompu.")
    return found


async def _complete_teacher_file(
    ctx: SeedContext,
    teacher_id: int,
    cnps: str,
    authorization: str,
    genre: str,
    contract: TeacherContract,
) -> None:
    """Complète les champs que la DEEP réclame et qu'aucun écran ne saisit."""
    teacher = await ctx.db.get(TeacherProfile, teacher_id)
    if teacher is None:
        return
    teacher.cnps_number = teacher.cnps_number or cnps
    teacher.teaching_authorization_number = teacher.teaching_authorization_number or authorization
    teacher.genre = teacher.genre or genre
    teacher.contract_type = teacher.contract_type or contract.value


async def _complete_pre_existing_teachers(ctx: SeedContext) -> None:
    """Les enseignants déjà en base méritent le même dossier complet.

    Sans eux, le tableau « répartition par type de contrat » compte une
    poignée de lignes vides au milieu d'une équipe renseignée : et c'est
    précisément ce que l'inspection remarque.
    """
    stmt = select(TeacherProfile).where(
        (TeacherProfile.contract_type.is_(None))
        | (TeacherProfile.genre.is_(None))
        | (TeacherProfile.cnps_number.is_(None))
        | (TeacherProfile.teaching_authorization_number.is_(None))
    )
    for offset, teacher in enumerate((await ctx.db.execute(stmt)).scalars().all(), start=901):
        cnps, authorization = _identity_numbers(offset)
        teacher.cnps_number = teacher.cnps_number or cnps
        teacher.teaching_authorization_number = (
            teacher.teaching_authorization_number or authorization
        )
        teacher.genre = teacher.genre or ("F" if offset % 2 == 0 else "M")
        teacher.contract_type = (
            teacher.contract_type or CONTRACT_CYCLE[offset % len(CONTRACT_CYCLE)].value
        )
        ctx.tally("dossiers enseignants complétés")


async def ensure_staff(ctx: SeedContext) -> None:
    """Le personnel administratif, un compte par métier.

    Chaque métier a son propre rôle d'accès : c'est ce qui permet de montrer,
    pendant la démonstration, que la caissière ne voit pas ce que voit le
    comptable, et que l'éducateur n'ouvre pas la caisse.
    """
    existing_emails = set((await ctx.db.execute(select(User.email))).scalars().all())

    for rank, (role, position, genre) in enumerate(STAFF_ROLES, start=1):
        first_name, last_name = names.pick_full_name(ctx.rng, genre)
        email = f"{role}{rank}@{STAFF_DOMAIN}"

        if email in existing_emails:
            staff_id, user_id = await _staff_ids_for_email(ctx, email)
        else:
            response = await admin_service.create_staff(
                ctx.db,
                StaffCreate(
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    password=DEMO_PASSWORD,
                    position=position,
                    phone=names.phone_number(ctx.rng),
                    role=role,
                ),
                created_by=ctx.actor_id,
            )
            staff_id = response.id
            user_id = await _user_id_for_email(ctx, email)
            ctx.tally("personnel")

        profile = await ctx.db.get(StaffProfile, staff_id)
        if profile is not None:
            cnps, authorization = _identity_numbers(800 + rank)
            profile.cnps_number = profile.cnps_number or cnps
            if role in {"director", "studies_director"}:
                profile.teaching_authorization_number = (
                    profile.teaching_authorization_number or authorization
                )

        ctx.staff_by_role.setdefault(role, staff_id)
        ctx.staff_user_by_role.setdefault(role, user_id)
        ctx.staff_by_role[f"{role}:{rank}"] = staff_id
        ctx.staff_user_by_role[f"{role}:{rank}"] = user_id

    await ctx.db.commit()


async def _staff_ids_for_email(ctx: SeedContext, email: str) -> tuple[int, int]:
    stmt = (
        select(StaffProfile.id, User.id)
        .join(User, User.id == StaffProfile.user_id)
        .where(User.email == email)
    )
    row = (await ctx.db.execute(stmt)).first()
    if row is None:
        raise RuntimeError(f"Compte {email} présent sans profil personnel : semis interrompu.")
    return int(row[0]), int(row[1])


async def _user_id_for_email(ctx: SeedContext, email: str) -> int:
    found = (await ctx.db.execute(select(User.id).where(User.email == email))).scalar_one_or_none()
    if found is None:
        raise RuntimeError(f"Compte {email} introuvable après création : semis interrompu.")
    return int(found)


async def run(ctx: SeedContext) -> None:
    await ensure_teachers(ctx)
    await ensure_staff(ctx)
