"""Helpers PDF partagés : escape HTML, format Decimal, embed image, headers officiels.

Extrait du legacy `pdf_service.py` pour respecter no-god-code et permettre
la réutilisation par tous les sous-modules du package `pdf`.
"""

from __future__ import annotations

import base64
import enum
import logging
import os
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mention d'etat civil absente sur une piece officielle
# ---------------------------------------------------------------------------

# Points de suite. Une piece officielle ivoirienne doit porter la mention
# « ne(e) le ... a ... » : la supprimer rend le document non conforme, et y
# imprimer « None », un vide ou une valeur approchante le rend faux. On imprime
# donc la ligne a completer et parapher a la main au secretariat, comme sur les
# imprimes prefectoraux.
OFFICIAL_BLANK = "……………………"


def birth_mention(student: Mapping[str, Any]) -> tuple[str, str]:
    """Date et lieu de naissance prêts à imprimer sur une pièce officielle.

    Retourne `(date, lieu)` déjà formatés. Deux garanties, qui sont la
    raison d'être de cette fonction :

    - **aucun repli sur `city` / `commune`.** Ce sont le domicile actuel.
      Un élève né à Bouaké et domicilié à Cocody n'est pas « né à Cocody »,
      et un certificat qui l'affirme est un faux, opposable à
      l'administration qui le réclame.
    - **jamais `None` ni de vide.** L'information manquante sort en points
      de suite, la ligne que le secrétariat complète et paraphe à la main,
      comme sur les imprimés préfectoraux. Retirer la mention rendrait le
      document non conforme ; la laisser vide le rendrait illisible.
    """
    birth_date = student.get("birth_date")
    date_str = birth_date.strftime("%d/%m/%Y") if birth_date else OFFICIAL_BLANK
    place = (student.get("birth_place") or "").strip() or OFFICIAL_BLANK
    return date_str, place


# ---------------------------------------------------------------------------
# Enum value extractor — fix bug "PaymentMethod.CASH" affiché brut
# ---------------------------------------------------------------------------


def enum_value(v: Any) -> Any:
    """Extrait `.value` si v est un `enum.Enum`, sinon retourne v inchangé.

    Bug fondateur : SQLAlchemy `SAEnum(enum_cls, ...)` retourne l'enum
    Python object à la lecture (ex: `PaymentMethod.CASH`). Quand on
    `str()` cet objet → `"PaymentMethod.CASH"`. Le PDF affiche cette
    string brute au lieu de la vraie valeur (`"cash"`) puis du label FR
    (`"Espèces"`). Toujours passer par ce helper dans les compositors.
    """
    if isinstance(v, enum.Enum):
        return v.value
    return v


# ---------------------------------------------------------------------------
# Image embedding (logo, signature, etc.)
# ---------------------------------------------------------------------------

_UPLOAD_ROOT = "/tmp/klassci-uploads"
_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "svg": "image/svg+xml",
}


def image_to_datauri(url_or_path: str | None) -> str | None:
    """Resolve an image URL/path and return a `data:image/...;base64,...` URI.

    Accepts:
    - relative URLs like `/uploads/photos/abc.png` (resolved against `_UPLOAD_ROOT`)
    - absolute filesystem paths
    Returns None if the file cannot be found or read.

    WeasyPrint embeds inline data URIs reliably across multi-tenant containers,
    avoiding the brittleness of file:// or HTTP-fetched assets.
    """
    if not url_or_path:
        return None

    candidates: list[str] = []
    if url_or_path.startswith("/uploads/"):
        candidates.append(os.path.join(_UPLOAD_ROOT, url_or_path[len("/uploads/") :]))
    else:
        candidates.append(url_or_path)

    for path in candidates:
        try:
            if not os.path.exists(path):
                continue
            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else "png"
            mime = _MIME_BY_EXT.get(ext, "image/png")
            return f"data:{mime};base64,{encoded}"
        except OSError as exc:
            logger.warning("Could not embed image %s: %s", path, exc)
            continue
    return None


# ---------------------------------------------------------------------------
# Escapes & formatters
# ---------------------------------------------------------------------------


def esc(val: Any) -> str:
    """Escape HTML characters."""
    if val is None:
        return ""
    return (
        str(val)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_decimal(val: Decimal | None) -> str:
    if val is None:
        return "-"
    return f"{val:.2f}"


def format_xof(val: Decimal | int | float | None) -> str:
    """Formate un montant XOF avec séparateurs français (espaces insécables)."""
    if val is None:
        return "-"
    return f"{Decimal(val):,.0f}".replace(",", " ")


# ---------------------------------------------------------------------------
# Officiels — header République de Côte d'Ivoire + entête école + footer signature
# ---------------------------------------------------------------------------

CI_HEADER = """
<div style="text-align:center; margin-bottom:10px;">
    <div style="font-size:11px; text-transform:uppercase;">
        Republique de Cote d'Ivoire
    </div>
    <div style="font-size:10px; font-style:italic; margin-bottom:4px;">
        Union &mdash; Discipline &mdash; Travail
    </div>
    <div style="font-size:10px;">
        Ministere de l'Education Nationale et de l'Alphabetisation
    </div>
</div>
"""


BASE_STYLES = """
<style>
    @page { margin: 15mm; }
    body { font-family: 'Helvetica', 'Arial', sans-serif; font-size: 11px; color: #222; }
    h1 { font-size: 16px; text-align: center; margin: 10px 0; }
    h2 { font-size: 13px; margin: 8px 0; }
    table { width: 100%; border-collapse: collapse; margin: 8px 0; }
    th, td { border: 1px solid #555; padding: 4px 6px; text-align: left; font-size: 10px; }
    th { background: #e9e9e9; font-weight: bold; }
    .text-center { text-align: center; }
    .text-right { text-align: right; }
    .school-header { text-align: center; margin-bottom: 8px; }
    .school-name { font-size: 14px; font-weight: bold; }
    .ministry-code { font-size: 10px; color: #555; }
    .signatures { display: flex; justify-content: space-between; margin-top: 30px; }
    .signature-block { text-align: center; width: 30%; }
    .signature-line { border-top: 1px solid #333; margin-top: 40px; padding-top: 4px; }
    .info-row { margin: 3px 0; font-size: 11px; }
    .mention-badge { font-weight: bold; padding: 2px 8px; border-radius: 3px; }
</style>
"""


def school_header_html(settings: dict[str, Any]) -> str:
    """Render the official document header with logo, school name, ministry code.

    Defensive `.get()` access on settings keys: missing keys are tolerated and
    the corresponding section is simply omitted (graceful degrade for tenants
    that have not configured logo/address yet).
    """
    school_name = settings.get("school_name", "Etablissement")
    ministry_code = settings.get("ministry_code")
    address = settings.get("address")
    logo_datauri = image_to_datauri(settings.get("logo_url"))

    code_line = ""
    if ministry_code:
        code_line = f'<div class="ministry-code">Code : {esc(ministry_code)}</div>'

    address_line = ""
    if address:
        address_line = f'<div style="font-size:9px; color:#555;">{esc(address)}</div>'

    logo_block = ""
    if logo_datauri:
        logo_block = (
            f'<div style="text-align:center; margin-bottom:6px;">'
            f'<img src="{logo_datauri}" alt="Logo" '
            f'style="max-height:60px; max-width:140px;" /></div>'
        )

    return f"""
    {CI_HEADER}
    {logo_block}
    <div class="school-header">
        <div class="school-name">{esc(school_name)}</div>
        {code_line}
        {address_line}
    </div>
    """


def official_footer_html(settings: dict[str, Any]) -> str:
    """Render the official signature block (head master name, title, signature image).

    Returns empty string if neither head_master_name nor signature_image_url
    is configured. Used by certificate / attestation / bulletins requiring
    formal sign-off (PR #105+).
    """
    head_master_name = settings.get("head_master_name")
    head_master_title = settings.get("head_master_title") or "Le Chef d'Etablissement"
    signature_datauri = image_to_datauri(settings.get("signature_image_url"))

    if not head_master_name and not signature_datauri:
        return ""

    signature_img = ""
    if signature_datauri:
        signature_img = (
            f'<div style="margin: 6px 0;">'
            f'<img src="{signature_datauri}" alt="Signature" '
            f'style="max-height:60px; max-width:200px;" /></div>'
        )

    return f"""
    <div style="margin-top: 30px; text-align: center;">
        <div style="font-style: italic;">{esc(head_master_title)}</div>
        {signature_img}
        <div style="font-weight: bold;">{esc(head_master_name or "")}</div>
    </div>
    """


# ---------------------------------------------------------------------------
# Aliases legacy (les modules historiques importent avec un underscore prefix)
# ---------------------------------------------------------------------------

_esc = esc
_format_decimal = format_decimal
_image_to_datauri = image_to_datauri
_school_header_html = school_header_html
_official_footer_html = official_footer_html
_BASE_STYLES = BASE_STYLES
_CI_HEADER = CI_HEADER
