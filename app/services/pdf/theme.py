"""Design system PDF — palette dynamique par école + status labels.

Architecture (refactor 2026-05-18) :
- `PDFTheme` est instanciée depuis `school_settings` au moment de
  composer chaque PDF. Si `primary_color` / `accent_color` sont définis
  dans `school_settings`, ils overrident la palette KLASSCI par défaut.
- Tous les composants `app/services/pdf/components.py` reçoivent une
  instance `PDFTheme` et appliquent les couleurs via CSS variables.
- Les status labels (FR) et les méthodes de paiement restent globaux
  (vocabulaire métier, pas customisable par école).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Palette KLASSCI par défaut (fallback si school.primary_color is NULL)
# ---------------------------------------------------------------------------

DEFAULT_PRIMARY = "#0F3F8C"  # Bleu KLASSCI
DEFAULT_ACCENT = "#F58220"  # Orange KLASSCI


@dataclass(frozen=True)
class PDFTheme:
    """Theme dynamique appliqué à un document PDF.

    Construit via `PDFTheme.from_school(school_dict)` qui merge les
    couleurs école avec les fallbacks KLASSCI. Toutes les valeurs sont
    des strings CSS valides (hex `#RRGGBB`, named colors, etc.).
    """

    primary: str = DEFAULT_PRIMARY
    accent: str = DEFAULT_ACCENT
    ink: str = "#0F172A"  # texte principal
    muted: str = "#64748B"  # texte secondaire
    border: str = "#E2E8F0"  # lignes neutres
    soft_bg: str = "#F8FAFC"  # fond zebra
    success: str = "#10B981"  # paiement OK
    warn: str = "#F59E0B"  # partial / warning
    danger: str = "#EF4444"  # erreur
    info: str = "#3B82F6"  # info neutre
    font_family: str = "'Helvetica', 'Arial', sans-serif"
    font_serif: str = "'Georgia', 'Times New Roman', serif"

    @classmethod
    def from_school(cls, school: dict[str, Any] | None) -> PDFTheme:
        """Instancie le theme depuis school_settings. Tous les overrides optionnels."""
        if not school:
            return cls()
        return cls(
            primary=school.get("primary_color") or DEFAULT_PRIMARY,
            accent=school.get("accent_color") or DEFAULT_ACCENT,
        )

    @property
    def primary_light(self) -> str:
        """Variante claire du primary pour gradients (8% opacity simulée)."""
        return self._hex_with_alpha(self.primary, 0.08)

    @property
    def accent_light(self) -> str:
        return self._hex_with_alpha(self.accent, 0.12)

    @staticmethod
    def _hex_with_alpha(hex_color: str, alpha: float) -> str:
        """Compose une couleur RGBA depuis un hex + alpha. Fallback hex inchangé si invalide."""
        if not hex_color.startswith("#") or len(hex_color) != 7:
            return hex_color
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            return f"rgba({r}, {g}, {b}, {alpha:.2f})"
        except ValueError:
            return hex_color


# ---------------------------------------------------------------------------
# Aliases rétrocompat (modules legacy qui importent `_PRIMARY` / `_ACCENT`)
# ---------------------------------------------------------------------------

_PRIMARY = DEFAULT_PRIMARY
_ACCENT = DEFAULT_ACCENT
PRIMARY = DEFAULT_PRIMARY
ACCENT = DEFAULT_ACCENT


# ---------------------------------------------------------------------------
# Status labels FR (vocabulaire métier — pas customisable par école)
# ---------------------------------------------------------------------------

STATUS_LABELS_FR: dict[str, str] = {
    "paid": "Payé",
    "partial": "Partiel",
    "pending": "En attente",
    "waived": "Exonéré",
    "completed": "Validé",
    "cancelled": "Annulé",
    "refunded": "Remboursé",
    "failed": "Échoué",
    # enrollment statuses
    "valide": "Validée",
    "prospect": "Prospect",
    "en_validation": "En validation",
    "rejete": "Rejetée",
    "annule": "Annulée",
}


PAYMENT_METHOD_LABELS_FR: dict[str, str] = {
    "cash": "Espèces",
    "mobile_money": "Mobile Money",
    "bank_transfer": "Virement bancaire",
    "cheque": "Chèque",
}


MENTION_LABELS_FR: dict[str, str] = {
    # Noms de membres d'enum
    "TRES_BIEN": "Très Bien",
    "BIEN": "Bien",
    "ASSEZ_BIEN": "Assez Bien",
    "PASSABLE": "Passable",
    "MEDIOCRE": "Médiocre",
    # Valeurs d'enum
    "TB": "Très Bien",
    "B": "Bien",
    "AB": "Assez Bien",
    "P": "Passable",
    "M": "Médiocre",
}


def status_label(key: str) -> str:
    """Renvoie le label FR d'un status (paid → Payé). Fallback sur la clé."""
    return STATUS_LABELS_FR.get(key, key)


def method_label(key: str) -> str:
    """Renvoie le label FR d'une méthode (cash → Espèces). Fallback sur la clé."""
    return PAYMENT_METHOD_LABELS_FR.get(key, key)


def mention_label(value: Any) -> str:
    """Renvoie le label FR d'une mention.

    Accepte un enum `Mention`, sa `.value` (ex: "TB"), ou une chaîne brute
    comme "Mention.TRES_BIEN". Nettoie le préfixe enum puis cherche le label
    en l'état et en majuscules. Fallback sur la chaîne nettoyée.
    """
    cleaned = str(value).split(".")[-1].strip()
    if not cleaned:
        return ""
    return MENTION_LABELS_FR.get(cleaned) or MENTION_LABELS_FR.get(cleaned.upper()) or cleaned


def appreciation_label(average: Any) -> str:
    """Appréciation par matière déduite de la moyenne /20 (échelle scolaire CI).

    Distincte de la mention générale : qualifie le niveau dans UNE matière.
    Accepte un nombre, un Decimal ou une chaîne numérique ; renvoie "—" si
    la moyenne est absente ou non interprétable.
    """
    if average is None or average == "":
        return "—"
    try:
        value = float(average)
    except (TypeError, ValueError):
        return "—"
    if value >= 16:
        return "Excellent"
    if value >= 14:
        return "Très bien"
    if value >= 12:
        return "Bien"
    if value >= 10:
        return "Assez bien"
    if value >= 8:
        return "Passable"
    return "Insuffisant"
