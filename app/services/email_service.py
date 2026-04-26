"""Service d'envoi d'emails via SMTP — multipart text+HTML + templates."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

# Chemin racine des templates email — relatif au package app/
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"


def _is_configured() -> bool:
    """Vérifie que les paramètres SMTP sont renseignés."""
    return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)


def _render_template(template_name: str, **context: object) -> str:
    """Charge un template depuis app/templates/emails/ et substitue les placeholders.

    Format des placeholders : {nom} (str.format_map). Les clés manquantes lèvent
    KeyError pour échouer fort si un template oublie une variable.
    """
    path = _TEMPLATES_DIR / template_name
    template = path.read_text(encoding="utf-8")
    return template.format_map(context)


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> bool:
    """Envoie un email multipart (HTML + texte) via SMTP.

    Retourne True si l'envoi réussit, False sinon.
    Si SMTP n'est pas configuré, log un warning et retourne False
    (best-effort — n'interrompt pas le flow appelant).
    """
    if not _is_configured():
        logger.warning("SMTP not configured — email to %s skipped", to_email)
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # Le client email préfère la dernière version attachée — on attache le texte
    # d'abord (fallback) puis le HTML (préféré).
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM_EMAIL, to_email, msg.as_string())
        logger.info("Email sent to %s — subject: %s", to_email, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False


def send_tenant_welcome(
    *,
    admin_email: str,
    admin_first_name: str,
    school_name: str,
    tenant_slug: str,
    temp_password: str,
    base_domain: str = "college.klassci.com",
) -> bool:
    """Envoie l'email de bienvenue au nouvel admin tenant après provisioning.

    Inclut URL personnalisée du tenant, identifiants temporaires, et CTA login.
    Best-effort : si SMTP indisponible, log mais ne raise pas (le tenant existe
    déjà en DB, on ne veut pas rollback à cause d'un email).
    """
    tenant_url = f"https://{tenant_slug}.{base_domain}"
    context = {
        "admin_first_name": admin_first_name or "Administrateur",
        "school_name": school_name,
        "admin_email": admin_email,
        "temp_password": temp_password,
        "tenant_url": tenant_url,
    }

    html_body = _render_template("tenant_welcome.html", **context)
    text_body = _render_template("tenant_welcome.txt", **context)

    subject = f"Bienvenue sur KLASSCI College — {school_name}"
    return send_email(admin_email, subject, html_body, text_body)
