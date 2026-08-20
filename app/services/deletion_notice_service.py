"""Le courriel qui garde la mémoire d'une suppression.

Un journal d'audit vit dans la base : celui qui peut effacer une fiche peut,
en principe, atteindre la trace de son geste. Un courriel, lui, est déjà
parti. Il dort dans la boîte de réception du chef d'établissement, hors du
logiciel, et personne ne l'y rattrape.

D'où ce service. À chaque mise à la corbeille et à chaque suppression
définitive, il compose et envoie un message qui dit **qui**, **quand**,
**quoi exactement**, **pourquoi**, et **ce qui est parti avec**.

Deux principes de construction :

- **Le message est lu par un chef d'établissement**, pas par un
  développeur : français, accents, aucun identifiant technique mis en avant,
  aucune abréviation interne.
- **L'envoi ne bloque jamais la suppression.** Une boîte pleine, un serveur
  SMTP en panne ou une clé MailPulse périmée ne doivent pas empêcher une
  secrétaire de corriger une fiche créée en double. En cas d'échec, on
  journalise et on continue : c'est le seul arbitrage possible entre
  « la trace part » et « le logiciel reste utilisable ».
"""

import logging
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import SchoolSettings
from app.models.user import User
from app.services import email_service
from app.services.archive_service import ArchiveOutcome

logger = logging.getLogger(__name__)

#: Libellés lisibles des types d'entité. Le journal parle en « student » ;
#: une directrice, non.
_ENTITY_LABELS = {
    "student": "Fiche élève",
    "parent": "Fiche parent",
    "teacher": "Fiche enseignant",
    "staff": "Fiche personnel",
    "enrollment": "Inscription",
}


def parse_recipients(raw: str | None) -> list[str]:
    """Découpe la liste saisie dans les paramètres de l'école.

    Séparateurs tolérés : virgule, point-virgule, retour à la ligne. Une
    école qui colle trois adresses depuis un tableur ne doit pas voir son
    courriel partir dans le vide parce qu'elle a utilisé le mauvais signe.

    Les entrées sans arobase sont écartées : ce n'est pas une validation
    d'adresse complète, seulement de quoi éviter qu'un nom saisi par erreur
    fasse échouer tout l'envoi.
    """
    if not raw:
        return []
    tokens = raw.replace(";", ",").replace("\n", ",").split(",")
    recipients: list[str] = []
    for token in tokens:
        address = token.strip()
        if "@" not in address:
            continue
        if address not in recipients:
            recipients.append(address)
    return recipients


def resolve_recipients(school: SchoolSettings) -> list[str]:
    """À qui part le courriel.

    D'abord la liste configurée par l'école. À défaut, l'adresse de
    l'établissement, qui est celle du chef d'établissement dans la quasi
    totalité des collèges — c'est un repli, pas un idéal : la liste dédiée
    reste ce qu'on demande de renseigner.
    """
    recipients = parse_recipients(school.deletion_notice_emails)
    if recipients:
        return recipients
    return parse_recipients(school.email)


def _entity_label(entity_type: str) -> str:
    return _ENTITY_LABELS.get(entity_type, "Fiche")


def _format_datetime(moment: datetime) -> str:
    """Date lisible à la française. Pas d'ISO : ce mail n'est pas un log."""
    return moment.strftime("%d/%m/%Y à %H:%M")


def compose_notice(
    outcome: ArchiveOutcome,
    *,
    school: SchoolSettings,
    actor_name: str,
    occurred_at: datetime,
) -> tuple[str, str, str]:
    """Compose (objet, corps texte, corps HTML).

    Séparé de l'envoi pour être relisible et testable sans réseau : le
    contenu de ce message est ce qui fera foi devant un fondateur d'école,
    il mérite d'être vérifié ligne à ligne.
    """
    school_name = school.school_name or "l'établissement"
    geste = "Suppression définitive" if outcome.permanent else "Mise à la corbeille"
    subject = f"{geste} — {outcome.label} — {school_name}"

    if outcome.permanent:
        consequence = (
            "Cette fiche et les données qui en dépendaient ont été détruites. "
            "Elle ne peut plus être restaurée."
        )
    else:
        consequence = (
            "Cette fiche a quitté les écrans mais rien n'a été détruit. "
            "Elle peut être restaurée depuis la corbeille."
        )

    lignes = [
        f"{geste} dans KLASSCI — {school_name}",
        "",
        f"Élément : {_entity_label(outcome.entity_type)} — {outcome.label}",
        f"Auteur : {actor_name}",
        f"Date : {_format_datetime(occurred_at)}",
        f"Motif indiqué : {outcome.reason}",
        "",
        consequence,
    ]

    if outcome.carried_away:
        lignes.append("")
        lignes.append("Emporté avec la fiche :")
        lignes.extend(f"  - {phrase}" for phrase in outcome.carried_away)
        lignes.append("")
        lignes.append(
            "Les versements encaissés, eux, sont conservés : ils portent "
            "désormais le nom et le matricule figés de l'élève, pour que les "
            "totaux de caisse déjà imprimés restent justes."
        )

    lignes.append("")
    lignes.append(
        "Ce message est envoyé automatiquement à chaque suppression. "
        "Conservez-le : il est la trace de l'acte hors du logiciel."
    )
    text_body = "\n".join(lignes)

    html_lignes = "".join(f"<li>{phrase}</li>" for phrase in outcome.carried_away)
    emporte_html = (
        f"<p><strong>Emporté avec la fiche :</strong></p><ul>{html_lignes}</ul>"
        "<p>Les versements encaissés, eux, sont conservés : ils portent désormais "
        "le nom et le matricule figés de l'élève, pour que les totaux de caisse "
        "déjà imprimés restent justes.</p>"
        if outcome.carried_away
        else ""
    )
    html_body = (
        f"<h2>{geste}</h2>"
        f"<p>{school_name}</p>"
        "<table cellpadding='6'>"
        f"<tr><td><strong>Élément</strong></td><td>{_entity_label(outcome.entity_type)} — "
        f"{outcome.label}</td></tr>"
        f"<tr><td><strong>Auteur</strong></td><td>{actor_name}</td></tr>"
        f"<tr><td><strong>Date</strong></td><td>{_format_datetime(occurred_at)}</td></tr>"
        f"<tr><td><strong>Motif indiqué</strong></td><td>{outcome.reason}</td></tr>"
        "</table>"
        f"<p>{consequence}</p>"
        f"{emporte_html}"
        "<p><em>Ce message est envoyé automatiquement à chaque suppression. "
        "Conservez-le : il est la trace de l'acte hors du logiciel.</em></p>"
    )

    return subject, text_body, html_body


async def _resolve_actor_name(db: AsyncSession, actor_id: int) -> str:
    """Nom lisible de l'auteur, ou son identifiant en dernier recours.

    On ne renonce jamais à nommer quelqu'un : « Utilisateur 12 » reste
    exploitable pour retrouver qui a agi, « inconnu » ne l'est pas.
    """
    if not actor_id:
        return "Utilisateur inconnu"
    user = (await db.execute(select(User).where(User.id == actor_id))).scalar_one_or_none()
    if user is None:
        return f"Utilisateur {actor_id}"

    for profile_attr in ("staff_profile", "teacher_profile"):
        profile = getattr(user, profile_attr, None)
        if profile is not None:
            nom = f"{profile.first_name} {profile.last_name}".strip()
            if nom:
                return f"{nom} ({user.email})"
    return user.email


async def send_deletion_notice(db: AsyncSession, outcome: ArchiveOutcome) -> bool:
    """Envoie le courriel de trace. Retourne `True` si au moins un envoi a abouti.

    Ne lève jamais : l'appelant est au milieu d'une suppression et ne doit pas
    voir son opération échouer parce qu'un serveur de messagerie est
    injoignable.
    """
    from app.services import admin_service

    school = await admin_service.get_school_settings(db)
    recipients = resolve_recipients(school)
    if not recipients:
        # Rien n'est configuré : on le dit fort dans les journaux plutôt que
        # de bloquer la suppression. Une école qui découvre qu'elle n'a pas
        # de destinataire préfère l'apprendre par un avertissement que par
        # une secrétaire empêchée de corriger une fiche.
        logger.warning(
            "Aucun destinataire pour le courriel de suppression "
            "(school_settings.deletion_notice_emails et .email sont vides) — "
            "%s %s non notifie",
            outcome.entity_type,
            outcome.entity_id,
        )
        return False

    occurred_at = outcome.occurred_at or datetime.now()
    actor_name = await _resolve_actor_name(db, outcome.actor_id)
    subject, text_body, html_body = compose_notice(
        outcome, school=school, actor_name=actor_name, occurred_at=occurred_at
    )

    return await _deliver(school, recipients, subject, text_body, html_body)


async def _deliver(
    school: SchoolSettings,
    recipients: Sequence[str],
    subject: str,
    text_body: str,
    html_body: str,
) -> bool:
    """Achemine le message par le transport déjà en place.

    MailPulse d'abord quand l'école l'a configuré : c'est son propre
    expéditeur, celui que ses destinataires reconnaissent. Sinon le SMTP de
    la plateforme, qui porte déjà les courriels administratifs.

    Le garde `mailpulse_real_workflows_enabled` n'est volontairement PAS
    consulté ici : il protège les messages envoyés aux parents. Une trace de
    suppression ne doit pas dépendre d'un interrupteur destiné aux familles.
    """
    from app.services.mailpulse.settings_service import build_client

    delivered = False

    client = build_client(school) if school.mailpulse_enabled else None
    if client is not None:
        for recipient in recipients:
            result = await client.send_message(
                channel="email",
                recipient=recipient,
                subject=subject,
                body=text_body,
                sender_email=school.mailpulse_sender_email,
                sender_name=school.mailpulse_sender_name,
            )
            delivered = delivered or result.ok
        if delivered:
            return True
        logger.warning("MailPulse n'a pas pu remettre le courriel de suppression — repli SMTP")

    for recipient in recipients:
        delivered = email_service.send_email(recipient, subject, html_body, text_body) or delivered

    if not delivered:
        logger.warning(
            "Le courriel de suppression n'a pu etre remis a aucun destinataire (%s)",
            ", ".join(recipients),
        )
    return delivered
