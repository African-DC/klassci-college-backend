"""Le point d'une catégorie de frais — document officiel de l'établissement.

Même gabarit que le journal des versements ou le bulletin : bandeau République,
en-tête à l'identité de l'école, couleurs et logo tirés de ses paramètres, pied
institutionnel. Ce n'est pas de la décoration. Ce document part chez un
prestataire pour justifier un virement, ou sur un bureau pour préparer des
relances : un tableau blanc sans en-tête n'est pas une pièce, c'est un
brouillon.

**Trois mentions portent la valeur du document, et aucune n'est décorative.**

L'avertissement de cloisonnement, quand le lecteur ne voit qu'une caisse : sans
lui, un état de guichet se lit comme le compte de l'école entière. Il est en
haut, avant les totaux, et répété en pied pour qui feuillette par la fin.

La phrase sur les dépôts : l'application enregistre un dépôt par ligne de
frais, jamais une quantité. Un document qui parlerait de « paquets » promettrait
un décompte que la base ne tient pas, et c'est sur cette promesse qu'on
commanderait une livraison.

Et l'identité du point — son année, son périmètre, sa caisse, son auteur, son
heure. Deux tirages qui ne les portent pas sont indiscernables une fois posés
côte à côte, et c'est l'un d'eux qu'on signe.

**Ses mots ne sont pas les siens** : ils viennent de
`app.services.payments.ledger_labels`, partagés avec le classeur. Ce module-là
dit aussi quelles colonnes le détail porte — le classeur en avait une de plus.
"""

from __future__ import annotations

from typing import Any

from app.services.fee_category_ledger import CategoryLedger
from app.services.payments import ledger_labels as mots
from app.services.pdf import components as ui
from app.services.pdf._helpers import format_xof
from app.services.pdf.theme import PDFTheme

#: La part de largeur de chaque colonne, quand elle est là. Les colonnes
#: présentes dépendent des droits du lecteur et de la catégorie : les parts
#: sont donc mises à l'échelle plutôt que figées en pourcentages, sans quoi une
#: colonne retirée laisserait un tableau qui ne remplit plus sa page.
_PARTS: dict[str, float] = {
    "eleve": 24,
    "matricule": 12,
    "classe": 11,
    "etat": 13,
    "du": 12,
    "entre": 14,
    "reste": 13,
    "depose": 11,
}

_STYLES = """
<style>
    /* L'en-tête se répète : une page de montants sans nom de colonne ne se
       relit pas, et ce document se relit devant un fournisseur. */
    .pdf-table thead { display: table-header-group; }
    .pdf-table tr { break-inside: avoid; }
    .pdf-section-title { break-after: avoid; }
</style>
"""


def _encadre(texte: str) -> str:
    """Un bloc d'avertissement : ce que le document ne dit pas, en évidence."""
    return (
        '<div style="border-left:3px solid var(--warn); background:var(--soft-bg);'
        ' padding:8px 12px; margin:10px 0; font-size:9.5px;">'
        f"{ui.esc(texte)}"
        "</div>"
    )


def _avertissement_cloisonnement(ledger: CategoryLedger) -> str:
    """La ligne qui empêche de prendre un état de guichet pour celui de l'école."""
    if ledger.consolide:
        return ""
    return _encadre(mots.AVERTISSEMENT_CAISSE)


def _avertissement_troncature(ledger: CategoryLedger) -> str:
    """Un document amputé qui se tait se signe comme s'il était complet."""
    if ledger.truncated_from is None:
        return ""
    return _encadre(mots.troncature_label(len(ledger.lignes), ledger.truncated_from))


def _note_depots(ledger: CategoryLedger) -> str:
    if not ledger.accepts_in_kind:
        return ""
    return (
        '<div class="muted" style="font-size:9px; margin:-4px 0 10px;">'
        f"{ui.esc(mots.depots_label(ledger.depots_en_nature))}"
        "</div>"
    )


def _reste_du(ledger: CategoryLedger) -> str:
    """Ce qui reste dû, et le fait que la période n'y change rien."""
    if ledger.total_restant_du is None or ledger.eleves_restant_du is None:
        return ""
    return (
        '<div class="muted text-center" style="font-size:9.5px; margin:-6px 0 12px;">'
        f"{ui.esc(mots.reste_du_label(ledger.eleves_restant_du, ledger.total_restant_du))}"
        "</div>"
    )


def _approvisionnement(ledger: CategoryLedger) -> str:
    """Combien d'articles l'ÉCOLE doit fournir, et avec quel argent.

    C'est la question qui fait tirer ce document. Un frais en nature se solde
    de deux façons, et elles n'appellent pas du tout la même suite : l'élève a
    apporté l'article — rien à faire ; il a payé — **l'école doit le lui
    fournir**, acheté chez le prestataire ; il n'a rien fait — on relance.

    Le document additionnait les deux premières dans un total en francs et un
    compte de dépôts, sans jamais dire le nombre qui déclenche la commande.

    Rien n'est recalculé ici : les trois seaux se lisent dans `compteurs`, qui
    porte déjà les états sur le périmètre entier.
    """
    if not ledger.accepts_in_kind or ledger.compteurs is None:
        return ""
    a_fournir = ledger.compteurs.get("paid", 0)
    apporte = ledger.compteurs.get("in_kind", 0)
    a_relancer = ledger.compteurs.get("pending", 0) + ledger.compteurs.get("partial", 0)
    if not (a_fournir or apporte or a_relancer):
        return ""

    def _case(valeur: int, libelle: str, mise: str = "") -> str:
        return (
            f'<td style="text-align:center; padding:6px 10px;{mise}">'
            f'<div style="font-size:15px; font-weight:700;">{valeur}</div>'
            f'<div class="muted" style="font-size:8.5px;">{ui.esc(libelle)}</div>'
            "</td>"
        )

    return (
        '<div style="border:1px solid var(--border); border-radius:4px;'
        ' padding:6px 4px; margin:6px 0 12px;">'
        '<table style="width:100%; border-collapse:collapse;"><tr>'
        + _case(a_fournir, "à fournir (payés en argent)", " font-weight:700;")
        + _case(apporte, "apportés par la famille")
        + _case(a_relancer, "ni payés ni apportés")
        + "</tr></table>"
        '<div class="muted" style="font-size:8.5px; text-align:center; padding:2px 8px 0;">'
        "Un frais ouvre droit à un article : « à fournir » est le nombre à commander "
        "chez le prestataire, et l’argent déjà encaissé ci-dessus est celui qui le paiera."
        "</div></div>"
    )


def _perimetre(ledger: CategoryLedger) -> str:
    """L'effectif lu, et ceux que ce frais ne facture pas.

    Sans ce compte, le document rétrécissait son propre dénominateur en
    silence : « tout le monde a payé » se lisait sur une liste où les élèves
    non facturés manquaient.
    """
    if not ledger.effectif_perimetre:
        return ""
    phrase = f"{ledger.effectif_perimetre} inscription(s) sur le périmètre lu"
    if ledger.eleves_sans_ligne:
        phrase += (
            f", dont {ledger.eleves_sans_ligne} que ce frais ne facture pas "
            "et qui ne figurent donc pas ci-dessous"
        )
    return (
        '<div class="muted text-center" style="font-size:9px; margin:-6px 0 10px;">'
        f"{ui.esc(phrase)}."
        "</div>"
    )


def _entetes(colonnes: tuple[mots.Colonne, ...]) -> list[Any]:
    """Les en-têtes du détail : les mots partagés, l'alignement du médium."""
    return [
        {"label": colonne.label, "align": "right"} if colonne.money else colonne.label
        for colonne in colonnes
    ]


def _largeurs(colonnes: tuple[mots.Colonne, ...]) -> list[str]:
    total = sum(_PARTS[colonne.key] for colonne in colonnes)
    return [f"{_PARTS[colonne.key] / total * 100:.1f}%" for colonne in colonnes]


def _cellule(ligne: Any, cle: str) -> Any:
    """La cellule d'une colonne, pour une ligne d'élève.

    La règle du tiret est celle du module de libellés : « — » dit qu'on ne
    sait pas, jamais qu'il n'y a rien. Un montant nul s'écrit donc « 0 »,
    comme dans le classeur — le PDF écrivait « — » sous une ligne soldée, et
    le même élève sortait « inconnu » ici et « soldé » là-bas.

    Aucune colonne de montant n'est servie vide : celle du reste dû n'existe
    pas quand personne ne peut la remplir.
    """
    if cle == "eleve":
        return f"{ligne.last_name} {ligne.first_name}".strip()
    if cle == "matricule":
        return {"value": ligne.student_matricule or mots.ABSENT, "type": "muted"}
    if cle == "classe":
        return {"value": ligne.class_name or mots.ABSENT, "type": "muted"}
    if cle == "etat":
        # La cle en valeur, le mot en `label` : `status_pill` fabrique sa
        # classe CSS a partir de la valeur, et un libelle francais y produisait
        # une classe inexistante — toute la colonne sortait sans couleur.
        return {
            "value": ligne.status,
            "label": mots.etat_label(ligne.status),
            "type": "pill",
        }
    if cle == "du":
        return {"value": format_xof(ligne.due), "type": "num"}
    if cle == "entre":
        return {"value": format_xof(ligne.paid), "type": "num-emphasis"}
    if cle == "reste":
        return {"value": format_xof(ligne.remaining), "type": "num"}
    return {
        "value": ligne.deposited_at.strftime("%d/%m/%Y") if ligne.deposited_at else mots.ABSENT,
        "type": "muted",
    }


def _lignes(ledger: CategoryLedger, colonnes: tuple[mots.Colonne, ...]) -> list[list[Any]]:
    return [[_cellule(ligne, colonne.key) for colonne in colonnes] for ligne in ledger.lignes]


def _total(ledger: CategoryLedger, colonnes: tuple[mots.Colonne, ...]) -> list[Any] | None:
    """La ligne de total, que seul le classeur portait.

    Elle décrit le PÉRIMÈTRE, pas la page : c'est le chiffre du haut de
    document, repris au bas du tableau pour qu'on n'ait pas à additionner la
    colonne à la main pour le retrouver. Quand la liste est tronquée, la
    mention de troncature dit que les deux ne peuvent pas se recouper.
    """
    if not ledger.lignes:
        return None
    cellules: list[Any] = []
    for colonne in colonnes:
        if colonne.key == "eleve":
            cellules.append({"value": mots.TOTAL_LABEL})
        elif colonne.key == "entre":
            cellules.append({"value": format_xof(ledger.total_en_argent), "type": "num-emphasis"})
        elif colonne.key == "reste" and ledger.total_restant_du is not None:
            cellules.append({"value": format_xof(ledger.total_restant_du), "type": "num"})
        else:
            # Une cellule vide, pas un tiret : le tiret dirait « on ne sait
            # pas » là où il n'y a simplement rien à totaliser.
            cellules.append({"value": "", "type": "text"})
    return cellules


def _identite(ledger: CategoryLedger) -> str:
    """Ce que le document nomme de lui-même : année, périmètre, caisse, filtres.

    Lu du CRITÈRE, jamais reconstitué depuis les lignes rendues : un filtre
    peut vider la liste sans que la classe cesse d'exister, et c'est justement
    au-dessus d'une liste vide qu'il faut dire de quoi elle est vide.
    """
    parties = [
        f"<strong>Année scolaire :</strong> {ui.esc(ledger.academic_year_name)}",
        f"<strong>Périmètre :</strong> {ui.esc(ledger.class_name)}",
        f"<strong>Caisse :</strong> {ui.esc(ledger.scope_label)}",
    ]
    filtres = mots.filters_label(state=ledger.etat_filtre, q=ledger.recherche)
    if filtres:
        parties.append(f'<span class="muted">Filtres appliqués : {ui.esc(filtres)}</span>')
    return "<br/>".join(parties)


def _signatures(ledger: CategoryLedger, theme: PDFTheme) -> str:
    """Qui signe quoi, selon ce que le document couvre.

    Faire signer « La Direction » sous l'état d'un guichet n'engage personne :
    la caissière arrête sa propre caisse, la comptabilité arrête le point de
    l'école. C'est la règle du bordereau journalier, et c'est le même geste
    comptable.
    """
    if ledger.consolide:
        roles = [
            {"role": "La Comptabilité", "name": ledger.issued_by},
            {"role": "La Direction"},
        ]
    else:
        roles = [
            {"role": "Le Caissier", "name": ledger.cashier_name or ledger.issued_by},
            {"role": "La Comptabilité"},
        ]
    return ui.signature_block(roles=roles, theme=theme)


def render_fee_category_ledger_html(ledger: CategoryLedger, school_settings: dict[str, Any]) -> str:
    """Compose le document, sans le convertir en PDF.

    Séparé de la conversion pour que la composition se vérifie sans dépendre
    des bibliothèques natives de rendu — celles-là mêmes qui manquent sur un
    poste Windows.
    """
    theme = PDFTheme.from_school(school_settings)
    school_name = school_settings.get("school_name") or ""

    colonnes = mots.colonnes(
        consolide=ledger.consolide,
        accepts_in_kind=ledger.accepts_in_kind,
    )
    detail = ui.section_title("Détail par élève", theme=theme) + ui.premium_table(
        headers=_entetes(colonnes),
        rows=_lignes(ledger, colonnes),
        theme=theme,
        empty_message=mots.AUCUNE_LIGNE,
        total_row=_total(ledger, colonnes),
        col_widths=_largeurs(colonnes),
    )

    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size="A4", margin="12mm")}{
        _STYLES
    }</head>
    <body>
        {ui.page_decoration(theme=theme, watermark_text=school_name)}
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type=f"POINT SUR : {ledger.category_name.upper()}",
            doc_subtitle=mots.period_label(ledger.date_from, ledger.date_to),
        )
    }
        {
        ui.meta_banner(
            _identite(ledger),
            ui.esc(mots.issued_label(ledger.issued_at, ledger.issued_by)),
            theme=theme,
        )
    }
        {_avertissement_cloisonnement(ledger)}
        {_avertissement_troncature(ledger)}
        {
        ui.amount_box(
            format_xof(ledger.total_en_argent),
            theme=theme,
            label=mots.entre_label(ledger.eleves_en_argent),
            currency="XOF",
        )
    }
        {_note_depots(ledger)}
        {_approvisionnement(ledger)}
        {_reste_du(ledger)}
        {_perimetre(ledger)}
        {detail}
        {_signatures(ledger, theme)}
        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note=mots.RAPPEL_ECOLE if ledger.consolide else mots.RAPPEL_CAISSE,
        )
    }
        </div>
    </body>
    </html>
    """


def generate_fee_category_ledger_pdf(
    ledger: CategoryLedger, school_settings: dict[str, Any]
) -> bytes:
    """Rend le document en PDF.

    Import differe : WeasyPrint tire des bibliotheques natives absentes des
    postes de developpement Windows. En tete de module, il rendait fausse la
    promesse de `render_fee_category_ledger_html` — dont tout l'interet est de
    se verifier sans elles — et celle de son fichier de test.
    """
    from weasyprint import HTML

    return HTML(string=render_fee_category_ledger_html(ledger, school_settings)).write_pdf()
