"""Sous-composants spécifiques à la fiche d'inscription.

Splittés de `enrollment_form.py` pour respecter no-god-code (<250 LOC par
fichier). Contient :
- `student_identity_block` : photo + identité (info_grid)
- `parent_card` : bloc parent individuel
- `parents_grid` : grille 3 parents (père/mère/tuteur)
- `fee_rows` + `fee_total_row` : rows de la table des frais
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._helpers import esc, format_decimal, image_to_datauri


def _initiales(nom: str) -> str:
    """Les initiales, quand aucune photo n'a ete deposee."""
    morceaux = [m for m in nom.replace("-", " ").split() if m]
    if not morceaux:
        return "?"
    if len(morceaux) == 1:
        return morceaux[0][:2].upper()
    return (morceaux[0][0] + morceaux[-1][0]).upper()


def student_identity_block(student: dict[str, Any]) -> str:
    """Photo (90×110) + info_grid identité élève."""
    last_name = esc(student.get("last_name", ""))
    first_name = esc(student.get("first_name", ""))
    full_name = f"{last_name} {first_name}".strip() or "—"
    genre_raw = student.get("genre") or ""
    genre_label = "Masculin" if genre_raw == "M" else ("Féminin" if genre_raw == "F" else "—")
    birth_date = student.get("birth_date")
    birth_str = birth_date.strftime("%d/%m/%Y") if birth_date else "—"
    birthplace = student.get("birth_place") or "—"
    city = student.get("city") or "—"
    commune = student.get("commune") or "—"
    address = student.get("address") or "—"

    photo_data = image_to_datauri(student.get("photo_url"))
    photo_html = (
        f'<img src="{photo_data}" alt="" '
        f'style="width:90px; height:110px; object-fit:cover; '
        f'border:1px solid var(--border); border-radius:4px;" />'
        if photo_data
        else (
            '<div style="width:90px; height:110px; background:var(--soft-bg); '
            "border:1px solid rgba(0, 0, 0, 0.10); border-radius:4px; "
            "display:flex; align-items:center; justify-content:center; "
            "color:var(--primary); font-family:var(--font-display); "
            f'font-size:30px; font-weight:700;">{esc(_initiales(full_name))}</div>'
        )
    )

    info = ui.info_table(
        items=[
            ("Nom et prénoms", full_name),
            ("Sexe", genre_label),
            ("Né(e) le", birth_str),
            ("À", birthplace),
            ("Ville · Commune", f"{city} · {commune}"),
            ("Adresse", address),
        ],
    )

    return f"""
    <table style="width:100%; border-collapse:collapse; margin-bottom:10px;">
      <tr>
        <td style="width:104px; padding:0 14px 0 0; vertical-align:top;">{photo_html}</td>
        <td style="vertical-align:top;">{info}</td>
      </tr>
    </table>
    """


def parent_card(label: str, parent: dict[str, Any] | None) -> str:
    """Bloc parent individuel (label uppercase + nom + tel + email)."""
    if not parent:
        return f"""
        <div style="flex:1; padding:8px 10px; border:1px solid var(--border);
                    border-radius:6px; background:var(--soft-bg);">
            <div style="font-size:9px; color:var(--primary); text-transform:uppercase;
                        letter-spacing:0.3px; font-weight:600; margin-bottom:3px;">
                {esc(label)}
            </div>
            <div style="color:var(--muted); font-style:italic; font-size:10px;">
                Non renseigné
            </div>
        </div>
        """
    name = esc(f"{parent.get('last_name', '')} {parent.get('first_name', '')}".strip()) or "—"
    phone = esc(parent.get("phone") or "—")
    email = esc(parent.get("email") or "—")
    relationship = esc(parent.get("relationship_label") or "")
    label_suffix = f" · {relationship}" if relationship else ""
    return f"""
    <div style="flex:1; padding:8px 10px; border:1px solid var(--border);
                border-radius:6px; background:var(--soft-bg);">
        <div style="font-size:9px; color:var(--primary); text-transform:uppercase;
                    letter-spacing:0.3px; font-weight:600; margin-bottom:3px;">
            {esc(label)}{label_suffix}
        </div>
        <div style="font-weight:bold; font-size:11px;">{name}</div>
        <div style="font-size:10px; color:var(--muted); margin-top:2px;">
            Tél : {phone} &nbsp; · &nbsp; Email : {email}
        </div>
    </div>
    """


def parents_grid(parents: list[dict[str, Any]]) -> str:
    """Trio Père / Mère / Tuteur (auto-extrait depuis la liste plate)."""
    pere = next(
        (p for p in parents if (p.get("relationship_label") or "").lower() == "père"),
        None,
    )
    mere = next(
        (p for p in parents if (p.get("relationship_label") or "").lower() == "mère"),
        None,
    )
    tuteur = next(
        (p for p in parents if p not in (pere, mere) and p is not None),
        None,
    )
    return (
        '<table style="width:100%; border-collapse:separate; border-spacing:10px 0;'
        ' margin:0 -10px 6px -10px;"><tr>'
        + f'<td style="width:33.33%; vertical-align:top;">{parent_card("Père", pere)}</td>'
        + f'<td style="width:33.33%; vertical-align:top;">{parent_card("Mère", mere)}</td>'
        + f'<td style="width:33.33%; vertical-align:top;">{parent_card("Tuteur", tuteur)}</td>'
        + "</tr></table>"
    )


def fee_rows_and_total(
    fees: list[dict[str, Any]],
) -> tuple[list[list[Any]], list[Any] | None]:
    """Compose rows + total_row pour la table des frais."""
    rows: list[list[Any]] = []
    total = Decimal("0")
    for f in fees:
        name = f.get("category_name", "")
        amount = f.get("amount")
        mandatory = f.get("is_mandatory", True)
        amount_str = format_decimal(amount) if isinstance(amount, Decimal) else str(amount or "—")
        kind = "Obligatoire" if mandatory else "Optionnel"
        rows.append(
            [
                name,
                {"value": kind, "type": "muted"},
                {"value": amount_str, "type": "num-emphasis"},
            ]
        )
        if isinstance(amount, Decimal):
            total += amount

    total_row: list[Any] | None = None
    if rows:
        total_row = [
            {"value": "TOTAL À PAYER", "type": "emphasis"},
            "",
            {"value": f"{format_decimal(total)} XOF", "type": "num-emphasis"},
        ]
    return rows, total_row


__all__ = [
    "fee_rows_and_total",
    "parent_card",
    "parents_grid",
    "student_identity_block",
]
