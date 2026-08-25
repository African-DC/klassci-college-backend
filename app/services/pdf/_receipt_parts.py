"""Composition d'un exemplaire de reçu : en-tête, versement, situation, pied.

Une moitié d'A4, soit 210 x 148 mm. Les deux moitiés de la page appellent ces
mêmes fonctions avec les mêmes données : c'est ce qui garantit que la famille
et le classeur repartent avec un document identique, au libellé d'exemplaire
près.

Utilisé par `receipt.py` seul.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.services.pdf._helpers import esc, format_xof, image_to_datauri
from app.services.pdf.theme import method_label, status_label

# Au-delà, les frais restants sont regroupés sur une ligne. Une école qui
# ventile sa scolarité en douze lignes ne fait pas déborder la moitié de page :
# elle lit ses six premiers frais par priorité, puis un total pour le reste.
# Six lignes couvrent la structure courante d'un collège ivoirien — Inscription,
# les trois trimestres, COGES, Tenue — qui doit tenir en entier.
MAX_FEE_LINES = 6

# Une moitié de page est un formulaire, pas un flux : chaque champ libre y a
# une longueur bornée. Sans ces bornes, une note de caisse un peu bavarde ou un
# libellé de frais à rallonge repousse les signatures sous le trait de coupe,
# et la famille repart avec un reçu sans signature ni référence.
MAX_FEE_NAME = 30
MAX_STUDENT_NAME = 58
MAX_NOTES = 80


def _clip(text: str, limit: int) -> str:
    """Tronque proprement au dernier espace avant la limite."""
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    coupe = value[: limit - 1].rstrip()
    if " " in coupe[limit // 2 :]:
        coupe = coupe[: coupe.rfind(" ")].rstrip()
    return f"{coupe}…"


def money(value: Decimal | int | float | None) -> str:
    """Montant à l'ivoirienne : séparateur espace et suffixe FCFA."""
    if value is None:
        return "—"
    return f"{format_xof(value)} FCFA"


def payment_method_display(key: str) -> str:
    """Libellé du moyen de paiement, sans liste figée dans le reçu.

    `method_label` porte les libellés connus et rend la clé brute pour les
    autres. Les moyens de paiement bougent — Wave, Orange Money, Moov —, et un
    reçu qui les énumérerait afficherait « inconnu » sur le premier ajout. On
    se contente donc de rendre lisible ce qui n'a pas encore de libellé, plutôt
    que d'imposer une liste de plus à tenir à jour.
    """
    label = method_label(key or "")
    if label != key:
        return label
    humanise = " ".join(w.capitalize() for w in (key or "").replace("_", " ").split())
    return humanise or "—"


def _logo_html(school: dict[str, Any]) -> str:
    logo = image_to_datauri(school.get("logo_url"))
    if logo:
        return f'<img src="{logo}" alt="Logo" />'
    words = [w for w in (school.get("school_name") or "E").split() if w]
    initials = "".join(w[0] for w in words[:2]).upper() or "E"
    return f'<div class="rc-monogram">{esc(initials)}</div>'


def header_html(school: dict[str, Any], *, doc_number: str, copy_label: str) -> str:
    """Bandeau d'identité : école à gauche, nature du document à droite."""
    meta: list[str] = []
    if school.get("address"):
        meta.append(esc(school["address"]))
    contact = " · ".join(esc(school[k]) for k in ("phone", "email") if school.get(k))
    code = school.get("ministry_code")
    line2 = " · ".join(p for p in ((f"Code MENA : {esc(code)}" if code else ""), contact) if p)
    if line2:
        meta.append(line2)
    meta_html = f'<div class="rc-school-meta">{"<br/>".join(meta)}</div>' if meta else ""

    return f"""
    <div class="rc-eyebrow">République de Côte d'Ivoire · Union — Discipline — Travail
        · Ministère de l'Éducation Nationale et de l'Alphabétisation</div>
    <table class="rc-head"><tr>
        <td class="rc-head-logo">{_logo_html(school)}</td>
        <td class="rc-head-id">
            <div class="rc-school">{esc(school.get("school_name") or "Établissement")}</div>
            {meta_html}
        </td>
        <td class="rc-doc">
            <div class="rc-doc-type">REÇU DE VERSEMENT</div>
            <div class="rc-doc-num">{esc(doc_number)}</div>
            <div class="rc-copy">{esc(copy_label)}</div>
        </td>
    </tr></table>
    <div class="rc-filet"></div>
    """


def _info_rows(items: list[tuple[str, str]]) -> str:
    rows = "".join(
        f'<tr><td class="rc-info-k">{esc(k)}</td><td class="rc-info-v">{v}</td></tr>'
        for k, v in items
        if v
    )
    return f'<table class="rc-info">{rows}</table>'


def payment_column_html(data: dict[str, Any]) -> str:
    """Colonne gauche : le versement du jour et ce qui l'identifie."""
    created_at = data.get("created_at")
    when = (
        created_at.strftime("%d/%m/%Y à %H:%M")
        if isinstance(created_at, datetime)
        else esc(str(created_at or ""))
    )
    items: list[tuple[str, str]] = [
        (
            "Élève",
            f'<span class="rc-strong">'
            f"{esc(_clip(data.get('student_name') or '—', MAX_STUDENT_NAME))}</span>",
        ),
    ]
    if data.get("class_name"):
        items.append(("Classe", esc(data["class_name"])))
    if data.get("academic_year_name"):
        items.append(("Année", esc(data["academic_year_name"])))
    items.append(("Date", when))
    items.append(("Moyen", esc(payment_method_display(data.get("method") or ""))))
    if data.get("reference"):
        items.append(("Référence", esc(data["reference"])))
    if data.get("fee_description"):
        items.append(("Imputation", esc(data["fee_description"])))
    status = data.get("status") or ""
    if status and status != "completed":
        items.append(("Statut", esc(status_label(status))))
    if data.get("notes"):
        items.append(("Notes", esc(_clip(data["notes"], MAX_NOTES))))

    return f"""
    <div class="rc-amount">
        <div class="rc-amount-label">{_libelle_montant(data)}</div>
        <div class="rc-amount-value">{esc(money(data.get("amount")))}</div>
    </div>
    {_info_rows(items)}
    """


def _situation_rows(situation: dict[str, Any]) -> str:
    lines = list(situation.get("lines") or [])
    shown, folded = lines[:MAX_FEE_LINES], lines[MAX_FEE_LINES:]

    rows: list[str] = []
    for line in shown:
        rows.append(
            f'<tr><td class="rc-l">{esc(_clip(line.get("name") or "—", MAX_FEE_NAME))}</td>'
            f"<td>{esc(format_xof(line.get('due')))}</td>"
            f"<td>{esc(format_xof(line.get('paid')))}</td>"
            f'<td class="rc-rest">{esc(format_xof(line.get("remaining")))}</td></tr>'
        )
    if folded:
        due = sum((Decimal(str(f.get("due") or 0)) for f in folded), Decimal("0"))
        paid = sum((Decimal(str(f.get("paid") or 0)) for f in folded), Decimal("0"))
        rest = sum((Decimal(str(f.get("remaining") or 0)) for f in folded), Decimal("0"))
        rows.append(
            f'<tr><td class="rc-l">Autres frais ({len(folded)})</td>'
            f"<td>{esc(format_xof(due))}</td><td>{esc(format_xof(paid))}</td>"
            f'<td class="rc-rest">{esc(format_xof(rest))}</td></tr>'
        )
    if not rows:
        rows.append(
            '<tr><td class="rc-l" colspan="4">Aucun frais n\'est encore inscrit '
            "sur cette inscription.</td></tr>"
        )

    rows.append(
        '<tr class="rc-total"><td class="rc-l">Total</td>'
        f"<td>{esc(format_xof(situation.get('total_due')))}</td>"
        f"<td>{esc(format_xof(situation.get('total_paid')))}</td>"
        f'<td class="rc-rest">{esc(format_xof(situation.get("total_remaining")))}</td></tr>'
    )
    return "".join(rows)


def _schedule_note(data: dict[str, Any]) -> str:
    """Une ligne d'échéancier, et rien de plus : le reste est déjà au tableau."""
    schedule = data.get("schedule") or {}
    if schedule.get("is_late") and schedule.get("late_amount"):
        return (
            '<div class="rc-note">Échéancier : <strong>retard de '
            f"{esc(money(schedule['late_amount']))}</strong> à ce jour.</div>"
        )
    due_date = schedule.get("next_due_date")
    if due_date:
        when = due_date.strftime("%d/%m/%Y") if isinstance(due_date, date) else str(due_date)
        amount = schedule.get("next_due_amount")
        montant = f" · <strong>{esc(money(amount))}</strong>" if amount else ""
        return f'<div class="rc-note">Prochaine échéance : {esc(when)}{montant}</div>'
    return ""


def situation_column_html(data: dict[str, Any]) -> str:
    """Colonne droite : ce qui est dû, ce qui est versé, ce qui reste."""
    situation = data.get("situation") or {}
    versement_du_jour = money(data.get("amount"))
    return f"""
    <div class="rc-title">Situation financière de l'élève</div>
    <table class="rc-sit">
        <colgroup>
            <col style="width:46%" /><col style="width:18%" />
            <col style="width:18%" /><col style="width:18%" />
        </colgroup>
        <thead><tr>
            <th class="rc-l">Frais</th><th>Dû</th><th>Versé</th><th>Reste</th>
        </tr></thead>
        <tbody>{_situation_rows(situation)}</tbody>
    </table>
    <div class="rc-note">{_note_cumul(data, versement_du_jour)}</div>
    {_schedule_note(data)}
    """


def key_figures_html(data: dict[str, Any]) -> str:
    """Les trois chiffres qu'une famille lit en premier, en gros caractères.

    Le tableau du dessus donne le détail par frais ; cette bande donne la
    réponse. « Il vous reste ceci à payer » est la seule phrase que le parent
    retiendra du guichet, elle ne doit pas se déduire d'une colonne.
    """
    situation = data.get("situation") or {}
    cells = (
        ("Total dû", situation.get("total_due"), False),
        ("Déjà versé", situation.get("total_paid"), False),
        ("Reste à payer", situation.get("total_remaining"), True),
    )
    tds = "".join(
        f'<td><div class="rc-key-label">{esc(label)}</div>'
        f'<div class="rc-key-value{" rc-focal" if focal else ""}">'
        f"{esc(money(value))}</div></td>"
        for label, value, focal in cells
    )
    return f'<table class="rc-keys"><tr>{tds}</tr></table>'


def _note_cumul(data: dict[str, Any], versement: str) -> str:
    """Ce que le cumul a le droit d'affirmer.

    « Versement du jour compris » devient faux dès que le versement est annulé :
    le total affiché juste au-dessus l'exclut, puisqu'il ne compte que les
    encaissements valides. La phrase nommait alors le montant annulé comme
    inclus, sur le document même qu'une famille brandira au guichet.
    """
    if data.get("status") == "cancelled":
        return (
            "Cumul de tous les versements encaissés. Le versement annulé "
            f"(<strong>{esc(versement)}</strong>) n'y figure pas."
        )
    return (
        "Cumul de tous les versements encaissés, versement du jour compris "
        f"(<strong>{esc(versement)}</strong>)."
    )


def _libelle_montant(data: dict[str, Any]) -> str:
    """Le bloc le plus visible de la page ne doit pas contredire le bandeau."""
    return "Montant annulé" if data.get("status") == "cancelled" else "Montant versé ce jour"


def _mention_de_pied(data: dict[str, Any]) -> str:
    """Ce que le pied de page a le droit d'affirmer.

    « Ce reçu fait foi de paiement » devient faux dès que le versement est
    annulé, et c'est justement le papier qu'on présentera au guichet pour
    soutenir le contraire.
    """
    if data.get("status") == "cancelled":
        return "Ce reçu est annulé et ne vaut pas justificatif de paiement."
    return "Ce reçu fait foi de paiement, à conserver."


def footer_html(data: dict[str, Any], school: dict[str, Any]) -> str:
    """Signatures + mention légale, sous les chiffres clés.

    La légende sous le trait du caissier n'est jamais vide : une cellule sans
    texte perd une ligne de hauteur et décale son trait par rapport à celui du
    parent, ce qui se voit immédiatement sur un document officiel.
    """
    cashier = esc(data.get("received_by_name") or "Nom et signature")
    school_name = esc(school.get("school_name") or "")
    return f"""
    <table class="rc-sign"><tr>
        <td>
            <div class="rc-sign-role">Le Caissier</div>
            <div class="rc-sign-line">{cashier}</div>
        </td>
        <td>
            <div class="rc-sign-role">Le Parent ou Tuteur</div>
            <div class="rc-sign-line">Nom et signature</div>
        </td>
    </tr></table>
    <table class="rc-foot"><tr>
        <td>{school_name} · {_mention_de_pied(data)}</td>
        <td class="rc-foot-right">{esc(data.get("document_reference") or "")}</td>
    </tr></table>
    """
