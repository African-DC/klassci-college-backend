"""Bulletin trimestriel — la feuille de registre d'un collège ivoirien.

Le bulletin n'est pas un écran imprimé, c'est un acte administratif. Une famille
le plie, le range, et le ressort trois ans plus tard pour une inscription. Son
autorité vient d'une grille réglée et dense, pas de cartes arrondies flottant
dans du blanc : sur papier, la carte arrondie se lit comme une page web sortie
à l'imprimante, et c'est exactement ce qui faisait bon marché.

D'où le parti pris, assumé et contraire au système de composants d'écran : un
seul cadre, des filets internes, aucun rayon, aucune ombre, la page remplie.
La densité EST la crédibilité. Ce qu'on lui ajoute de moderne tient dans le
soin typographique, pas dans les effets : chiffres tabulaires pour que les
colonnes de notes s'alignent au dixième, bandes de section fines plutôt que
grands titres, et une seule couleur d'accent.

L'accent est dépensé à un seul endroit : la moyenne générale. C'est le nombre
que le parent cherche en premier, et c'est le seul qu'on autorise à crier.

Structure reprise du bulletin trimestriel officiel ivoirien : identité avec
photographie, disciplines avec moyenne / coefficient / points / rang, total,
moyennes générales par trimestre, résultats de la classe, absences, puis
distinctions et sanctions à cocher, décision du conseil et signatures.
"""

from __future__ import annotations

from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._helpers import esc, format_decimal, image_to_datauri
from app.services.pdf.theme import PDFTheme

_DECISION_LABELS = {
    "passage": "Admis en classe supérieure",
    "repechage": "Repêché par le conseil",
    "redoublement": "Redouble la classe",
    "exclusion": "Exclu de l'établissement",
}

_GENRE_LABELS = {"M": "Masculin", "F": "Féminin"}

#: Cochées à la main par le conseil de classe, comme sur le document officiel.
#: Le système ne les décide pas : il imprime la case, le conseil tranche.
_DISTINCTIONS = ("Tableau d'honneur", "Encouragements", "Félicitations")
_SANCTIONS = ("Avertissement travail", "Avertissement conduite", "Blâme")


# ---------------------------------------------------------------------------
# Teintes
# ---------------------------------------------------------------------------


def _tint(hex_color: str, ratio: float) -> str:
    """Mélange une couleur avec du blanc — la trame de fond des cellules.

    Calculée depuis la couleur de l'établissement plutôt que figée : le
    document doit rester le sien, y compris dans ses gris.
    """
    couleur = (hex_color or "#0F3F8C").lstrip("#")
    if len(couleur) != 6:
        couleur = "0F3F8C"
    try:
        r, v, b = (int(couleur[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        r, v, b = 15, 63, 140
    melange = lambda c: round(c + (255 - c) * (1 - ratio))  # noqa: E731
    return f"#{melange(r):02x}{melange(v):02x}{melange(b):02x}"


# ---------------------------------------------------------------------------
# Fragments
# ---------------------------------------------------------------------------


def _initials(nom: str) -> str:
    """Les initiales, quand aucune photo n'a été déposée.

    Un cadre vide marqué « PHOTO » se lit comme un dossier incomplet. Deux
    lettres se lisent comme un choix.
    """
    morceaux = [m for m in nom.replace("-", " ").split() if m]
    if not morceaux:
        return "?"
    if len(morceaux) == 1:
        return morceaux[0][:2].upper()
    return (morceaux[0][0] + morceaux[-1][0]).upper()


def _photo_cell(nom: str, photo_url: str | None) -> str:
    """La photographie de l'élève, ou ses initiales.

    Le bulletin officiel lui réserve un cadre : c'est ce qui rend le document
    opposable au guichet quand un élève vient chercher le sien.
    """
    if photo_url:
        data = image_to_datauri(photo_url)
        if data:
            return f'<img class="bul-photo" src="{data}" alt="" />'
    return f'<div class="bul-photo bul-photo-init">{esc(_initials(nom))}</div>'


_REPUBLIQUE = "RÉPUBLIQUE DE CÔTE D'IVOIRE"
_DEVISE = "Union — Discipline — Travail"
_MINISTERE = "MINISTÈRE DE L'ÉDUCATION NATIONALE ET DE L'ALPHABÉTISATION"

_TRIMESTRE_LABELS = {1: "1er trimestre", 2: "2e trimestre", 3: "3e trimestre"}


def _masthead(school: dict[str, Any], d: dict[str, Any]) -> str:
    """L'en-tête du bulletin trimestriel ivoirien.

    Trois colonnes puis un bloc établissement encadré, comme le document
    officiel : l'autorité à gauche, le titre encadré au centre, l'année à
    droite. Ce n'est pas une préférence graphique — c'est la disposition qu'un
    parent, un proviseur et un inspecteur reconnaissent au premier coup d'œil,
    et la reconnaître fait la moitié de la confiance qu'on accorde au papier.
    """
    direction = (school.get("regional_direction") or school.get("ministry_code") or "").strip()
    direction_html = (
        f'<div class="bul-mh-autorite">DIRECTION RÉGIONALE {esc(direction)}</div>'
        if direction
        else ""
    )

    trimestre = d.get("trimester")
    trimestre_txt = _TRIMESTRE_LABELS.get(trimestre, f"Trimestre {trimestre}")

    logo = image_to_datauri(school.get("logo_url"))
    if logo:
        logo_html = f'<img class="bul-mh-logo-img" src="{logo}" alt="" />'
    else:
        mots = [m for m in (school.get("school_name") or "E").split() if m]
        logo_html = (
            f'<div class="bul-mh-mono">{esc("".join(m[0] for m in mots[:2]).upper() or "E")}</div>'
        )

    def ligne(cle: str, valeur: str) -> str:
        if not valeur:
            return ""
        return (
            f'<div class="bul-mh-ligne"><span class="bul-mh-cle">{esc(cle)}</span>'
            f'<span class="bul-mh-val">{esc(valeur)}</span></div>'
        )

    return f"""
    <table class="bul-mh"><tr>
      <td class="bul-mh-gauche">
        <div class="bul-mh-autorite">{esc(_REPUBLIQUE)}</div>
        <div class="bul-mh-devise">{esc(_DEVISE)}</div>
        <div class="bul-mh-autorite bul-mh-ministere">{esc(_MINISTERE)}</div>
        {direction_html}
      </td>
      <td class="bul-mh-centre">
        <div class="bul-mh-cartouche">
          <div class="bul-mh-titre">Bulletin trimestriel de notes</div>
          <div class="bul-mh-trimestre">{esc(trimestre_txt)}</div>
        </div>
      </td>
      <td class="bul-mh-droite">
        <div class="bul-mh-cle">Année scolaire</div>
        <div class="bul-mh-annee">{esc(d.get("academic_year_name") or "")}</div>
      </td>
    </tr></table>

    <table class="bul-etab"><tr>
      <td class="bul-etab-logo">{logo_html}</td>
      <td class="bul-etab-id">
        <div class="bul-etab-nom">{esc(school.get("school_name") or "Établissement")}</div>
        {ligne("Adresse", school.get("address") or "")}
        {ligne("Téléphone", school.get("phone") or "")}
      </td>
      <td class="bul-etab-admin">
        {ligne("Code", school.get("ministry_code") or "")}
        {ligne("Statut", school.get("status") or "Privé")}
        {ligne("E-mail", school.get("email") or "")}
      </td>
    </tr></table>
    """


def _coef(valeur: float) -> str:
    """Un coefficient s'écrit en entier.

    « 4.00 » est une fausse précision : un coefficient ne se divise pas, et la
    colonne devient illisible quand chaque ligne traîne deux décimales vides.
    """
    return str(int(valeur)) if float(valeur).is_integer() else format_decimal(valeur)


def _band(titre: str) -> str:
    """Bande de section : un filet teinté et une étiquette, pas un grand titre.

    Un titre de 16 points mangerait la moitié de la hauteur utile. La bande
    sépare aussi nettement et laisse la place aux chiffres.
    """
    return f'<div class="bul-bande">{esc(titre)}</div>'


def _identity(d: dict[str, Any]) -> str:
    """Identité de l'élève et sa photographie."""
    naissance = d.get("birth_date")
    ne_le = naissance.strftime("%d/%m/%Y") if hasattr(naissance, "strftime") else ""
    lieu = d.get("birth_place") or ""
    naissance_txt = ne_le or "—"

    paires = [
        ("Matricule", d.get("matricule") or "—"),
        ("Né(e) le", naissance_txt),
        ("Genre", _GENRE_LABELS.get(str(d.get("genre") or ""), "—")),
        ("Classe", d.get("class_name") or "—"),
        ("Année scolaire", d.get("academic_year_name") or "—"),
        ("Lieu de naissance", lieu or "—"),
    ]
    milieu = (len(paires) + 1) // 2
    colonnes = ""
    for groupe in (paires[:milieu], paires[milieu:]):
        lignes = "".join(
            f'<tr><td class="bul-cle">{esc(cle)}</td>'
            f'<td class="bul-val">{esc(str(valeur))}</td></tr>'
            for cle, valeur in groupe
        )
        colonnes += f'<td class="bul-id-col"><table class="bul-paires">{lignes}</table></td>'

    return (
        '<table class="bul-identite"><tr>'
        '<td class="bul-id-texte">'
        f'<div class="bul-nom">{esc(d.get("student_name") or "")}</div>'
        f'<table class="bul-id-grille"><tr>{colonnes}</tr></table>'
        "</td>"
        f'<td class="bul-id-photo">{_photo_cell(d.get("student_name") or "", d.get("photo_url"))}</td>'
        "</tr></table>"
    )


def _disciplines(subject_averages: list[dict[str, Any]]) -> str:
    """Le tableau des disciplines, et sa ligne de total.

    La colonne des points (moyenne × coefficient) est celle que le conseil
    additionne. Sans elle, une famille ne peut pas refaire le calcul de la
    moyenne générale, et le bulletin lui demande de croire sur parole.
    """
    lignes = ""
    coef_total = 0.0
    points_total = 0.0
    vu = False

    for sa in subject_averages:
        moyenne = sa.get("average")
        try:
            coef = float(sa.get("coefficient", 1) or 1)
        except (TypeError, ValueError):
            coef = 1.0
        points: float | None = None
        if moyenne is not None:
            try:
                points = float(moyenne) * coef
                points_total += points
                vu = True
            except (TypeError, ValueError):
                points = None
        coef_total += coef

        prof = sa.get("teacher_name") or ""
        rang = sa.get("rang") if sa.get("rang") is not None else sa.get("rank")
        moy_classe = sa.get("class_avg")

        lignes += (
            "<tr>"
            f'<td class="bul-matiere">{esc(sa.get("subject_name", ""))}</td>'
            f'<td class="bul-n bul-n-fort">{format_decimal(moyenne)}</td>'
            f'<td class="bul-n">{_coef(coef)}</td>'
            f'<td class="bul-n">{format_decimal(points) if points is not None else "—"}</td>'
            f'<td class="bul-n">{esc(str(rang)) if rang else "—"}</td>'
            f'<td class="bul-n bul-n-doux">'
            f"{format_decimal(moy_classe) if moy_classe is not None else '—'}</td>"
            f'<td class="bul-prof">{esc(prof)}</td>'
            f'<td class="bul-appr">{esc(ui.appreciation_label(moyenne))}</td>'
            "</tr>"
        )

    if not lignes:
        lignes = (
            '<tr><td colspan="7" class="bul-vide">Aucune note saisie pour ce trimestre.</td></tr>'
        )

    total = ""
    if vu:
        total = (
            '<tr class="bul-total">'
            '<td class="bul-matiere">Total</td>'
            '<td class="bul-n"></td>'
            f'<td class="bul-n">{_coef(coef_total)}</td>'
            f'<td class="bul-n">{format_decimal(points_total)}</td>'
            '<td class="bul-n"></td><td class="bul-n"></td>'
            '<td class="bul-prof"></td><td class="bul-appr"></td>'
            "</tr>"
        )

    return f"""
    <table class="bul-notes">
      <colgroup>
        <col style="width:24%"/><col style="width:8%"/><col style="width:6%"/>
        <col style="width:9%"/><col style="width:6%"/><col style="width:9%"/>
        <col style="width:20%"/><col style="width:18%"/>
      </colgroup>
      <thead><tr>
        <th class="bul-th-g">Discipline</th>
        <th>Moy. /20</th><th>Coef.</th><th>Points</th>
        <th>Rang</th><th>Moy. classe</th>
        <th class="bul-th-g">Professeur</th>
        <th class="bul-th-g">Appréciation</th>
      </tr></thead>
      <tbody>{lignes}{total}</tbody>
    </table>
    """


def _compartments(d: dict[str, Any]) -> str:
    """Les trois compartiments de synthèse, côte à côte.

    Moyennes par trimestre, résultats de la classe, assiduité. C'est le bloc
    qui répond à la question que le parent pose vraiment : « par rapport aux
    autres, et par rapport au trimestre dernier ».
    """
    stats = d.get("class_stats") or {}
    absences = d.get("absences") or {}
    trimestre = d.get("trimester")
    historique = d.get("trimester_history") or []

    if historique:
        lignes_trim = "".join(
            f'<tr><td class="bul-cle">{esc(str(t.get("label", "")))}</td>'
            f'<td class="bul-val bul-n">{format_decimal(t.get("average"))}</td>'
            f'<td class="bul-val bul-n">{esc(str(t.get("rank") or "—"))}</td></tr>'
            for t in historique
        )
    else:
        lignes_trim = (
            f'<tr><td class="bul-cle">Trimestre {esc(str(trimestre))}</td>'
            f'<td class="bul-val bul-n">{format_decimal(d.get("average"))}</td>'
            f'<td class="bul-val bul-n">{esc(str(d.get("rank") or "—"))}</td></tr>'
        )

    def couple(cle: str, valeur: str) -> str:
        return (
            f'<tr><td class="bul-cle">{esc(cle)}</td><td class="bul-val bul-n">{valeur}</td></tr>'
        )

    classe = (
        couple("Moyenne de la classe", format_decimal(stats.get("class_avg")))
        + couple("Plus forte moyenne", format_decimal(stats.get("class_max")))
        + couple("Plus faible moyenne", format_decimal(stats.get("class_min")))
    )
    assiduite = couple("Absences", str(int(absences.get("absent", 0) or 0))) + couple(
        "Retards", str(int(absences.get("late", 0) or 0))
    )

    return f"""
    <table class="bul-compartiments"><tr>
      <td class="bul-comp">
        <div class="bul-comp-titre">Moyennes générales</div>
        <table class="bul-paires">
          <tr><td class="bul-cle"></td><td class="bul-cle bul-n">Moy.</td>
              <td class="bul-cle bul-n">Rang</td></tr>
          {lignes_trim}
        </table>
      </td>
      <td class="bul-comp">
        <div class="bul-comp-titre">Résultats de la classe</div>
        <table class="bul-paires">{classe}</table>
      </td>
      <td class="bul-comp bul-comp-fin">
        <div class="bul-comp-titre">Assiduité</div>
        <table class="bul-paires">{assiduite}</table>
      </td>
    </tr></table>
    """


def _verdict(d: dict[str, Any]) -> str:
    """La ligne d'accent : la moyenne générale, le rang, la mention.

    Le seul endroit du document où la couleur d'accent est dépensée.
    """
    moyenne = format_decimal(d.get("average"))
    rang = d.get("rank")
    effectif = d.get("total_students") or 0
    rang_txt = f"{rang} <span class='bul-sur'>/ {effectif}</span>" if rang else "—"
    mention = ui.mention_label(d.get("mention")) if d.get("mention") else "—"
    return f"""
    <table class="bul-verdict"><tr>
      <td class="bul-verdict-cle">
        <div class="bul-verdict-label">Moyenne générale</div>
        <div class="bul-verdict-nombre">{esc(moyenne)}<span class="bul-sur"> / 20</span></div>
      </td>
      <td class="bul-verdict-item">
        <div class="bul-verdict-label">Rang</div>
        <div class="bul-verdict-val">{rang_txt}</div>
      </td>
      <td class="bul-verdict-item">
        <div class="bul-verdict-label">Mention</div>
        <div class="bul-verdict-val">{esc(mention)}</div>
      </td>
    </tr></table>
    """


def _mentions_conseil(d: dict[str, Any]) -> str:
    """Distinctions et sanctions à cocher, puis la décision du conseil.

    Les cases sont imprimées vides : c'est le conseil de classe qui tranche,
    en séance, au stylo. Les pré-cocher depuis une moyenne ferait dire au
    système une décision qui ne lui appartient pas.
    """

    def cases(items: tuple[str, ...]) -> str:
        return "".join(
            f'<div class="bul-case"><span class="bul-carre"></span>{esc(x)}</div>' for x in items
        )

    decision = d.get("council_decision")
    decision_html = ""
    if decision:
        libelle = _DECISION_LABELS.get(str(decision), str(decision))
        decision_html = (
            '<div class="bul-decision">'
            '<span class="bul-decision-cle">Décision du conseil de classe</span>'
            f'<span class="bul-decision-val">{esc(libelle)}</span></div>'
        )

    commentaire = d.get("teacher_comment")
    commentaire_html = ""
    if commentaire:
        commentaire_html = (
            '<div class="bul-appreciation">'
            '<span class="bul-cle">Appréciation du professeur principal</span>'
            f'<div class="bul-appreciation-txt">{esc(commentaire)}</div></div>'
        )

    return f"""
    <table class="bul-conseil"><tr>
      <td class="bul-conseil-col">
        <div class="bul-comp-titre">Distinctions</div>
        {cases(_DISTINCTIONS)}
      </td>
      <td class="bul-conseil-col bul-comp-fin">
        <div class="bul-comp-titre">Sanctions</div>
        {cases(_SANCTIONS)}
      </td>
    </tr></table>
    {decision_html}
    {commentaire_html}
    """


def _signatures(d: dict[str, Any]) -> str:
    ville = (d.get("school_city") or "").strip()
    fait = f"Fait à {ville}, le ……………………" if ville else "Le ……………………"
    return f"""
    <table class="bul-signatures"><tr>
      <td><div class="bul-sig-role">Le Professeur principal</div></td>
      <td><div class="bul-sig-role">Le Parent ou Tuteur</div></td>
      <td class="bul-comp-fin">
        <div class="bul-sig-role">Le Chef d'Établissement</div>
        <div class="bul-sig-lieu">{esc(fait)}</div>
      </td>
    </tr></table>
    """


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


def _styles(theme: PDFTheme) -> str:
    trame = _tint(theme.primary, 0.055)
    trame_forte = _tint(theme.primary, 0.10)
    filet = _tint(theme.primary, 0.30)
    return f"""
    <style>
      .bul {{
        --bul-trame: {trame};
        --bul-trame-forte: {trame_forte};
        --bul-filet: {filet};
        border: 1px solid var(--bul-filet);
        font-size: 9px;
      }}
      .bul table {{ width: 100%; border-collapse: collapse; }}
      .bul-n {{
        text-align: right;
        font-variant-numeric: tabular-nums;
        font-feature-settings: "tnum" 1;
      }}

      /* Masthead administratif */
      .bul-mh {{ margin-bottom: 7px; }}
      /* Selecteur descendant, pas `> tr` : un <tbody> implicite s'intercale
         entre la table et ses lignes, et le combinateur enfant ne trouvait
         rien. Les retraits tombaient donc a zero sur ces blocs. */
      .bul-mh td {{ vertical-align: top; }}
      .bul-mh-gauche {{ width: 40%; }}
      .bul-mh-centre {{ width: 36%; padding: 0 10px; }}
      .bul-mh-droite {{ width: 24%; text-align: right; }}
      /* La cle porte une marge droite pour les paires en ligne du bloc
         etablissement ; ici elle decalait « Annee scolaire » du bord et
         cassait l'alignement avec le millesime dessous. */
      .bul-mh-droite .bul-mh-cle {{ margin-right: 0; }}
      .bul-mh-autorite {{
        font-size: 7.5px; font-weight: 700; letter-spacing: 0.35px;
        text-transform: uppercase; color: var(--ink); line-height: 1.4;
      }}
      .bul-mh-ministere {{ margin-top: 2px; }}
      .bul-mh-devise {{
        font-size: 7.5px; font-style: italic; color: var(--muted); line-height: 1.4;
      }}
      .bul-mh-cartouche {{
        border: 1.2px solid var(--primary);
        padding: 5px 8px 6px;
        text-align: center;
      }}
      .bul-mh-titre {{
        font-family: var(--font-display);
        font-size: 10px; font-weight: 700; color: var(--primary);
        text-transform: uppercase; letter-spacing: 0.3px; line-height: 1.2;
      }}
      .bul-mh-trimestre {{
        font-family: var(--font-display);
        font-size: 12.5px; font-weight: 700; color: var(--ink);
        margin-top: 1px;
      }}
      .bul-mh-annee {{
        font-family: var(--font-display);
        font-size: 12px; font-weight: 700; color: var(--ink);
        font-variant-numeric: tabular-nums;
      }}

      /* Bloc établissement */
      .bul-etab {{
        width: 100%;
        border: 1px solid var(--bul-filet);
        margin-bottom: 7px;
      }}
      .bul-etab td {{ padding: 7px 11px; vertical-align: middle; }}
      .bul-etab-logo {{ width: 58px; }}
      .bul-mh-logo-img {{
        width: 46px; height: 46px; object-fit: contain;
        /* Noir pur a faible opacite : une teinte se lirait comme une
           salissure sur le bord de l'image. */
        border: 1px solid rgba(0, 0, 0, 0.10);
      }}
      .bul-mh-mono {{
        width: 46px; height: 46px;
        display: flex; align-items: center; justify-content: center;
        background: var(--primary); color: #fff;
        font-family: var(--font-display);
        font-size: 17px; font-weight: 700; letter-spacing: 0.5px;
      }}
      .bul-etab-id {{ border-right: 1px solid var(--bul-filet); padding-right: 14px; }}
      .bul-etab-admin {{ width: 38%; }}
      .bul-etab-nom {{
        font-family: var(--font-display);
        font-size: 13px; font-weight: 700; color: var(--primary);
        line-height: 1.2; margin-bottom: 3px;
      }}
      .bul-mh-ligne {{ line-height: 1.5; }}
      .bul-mh-cle {{
        font-size: 7px; font-weight: 700; letter-spacing: 0.6px;
        text-transform: uppercase; color: var(--muted); margin-right: 6px;
      }}
      .bul-mh-val {{ font-size: 8.5px; color: var(--ink); }}

      /* Bandes de section */
      .bul-bande {{
        background: var(--bul-trame-forte);
        border-top: 1px solid var(--bul-filet);
        border-bottom: 1px solid var(--bul-filet);
        padding: 3px 11px;
        font-size: 7.5px; font-weight: 700;
        letter-spacing: 1.1px; text-transform: uppercase;
        color: var(--primary);
      }}

      /* Identité */
      .bul-identite td {{ padding: 7px 11px; vertical-align: middle; }}
      .bul-nom {{
        font-family: var(--font-display);
        font-size: 15px; font-weight: 700; color: var(--primary);
        letter-spacing: 0.2px; margin-bottom: 5px;
      }}
      .bul-id-grille td.bul-id-col {{
        vertical-align: top; padding: 0 22px 0 0;
      }}
      .bul-paires td {{ padding: 1.2px 0; }}
      .bul-cle {{ color: var(--muted); padding-right: 12px; white-space: nowrap; }}
      .bul-val {{ font-weight: 600; color: var(--ink); white-space: nowrap; }}
      .bul-id-photo {{ width: 76px; text-align: right; }}
      .bul-photo {{
        width: 58px; height: 68px; object-fit: cover;
        border: 1px solid var(--bul-filet);
      }}
      .bul-photo-init {{
        display: flex; align-items: center; justify-content: center;
        background: var(--bul-trame); color: var(--primary);
        font-family: var(--font-display);
        font-size: 22px; font-weight: 700; letter-spacing: 1px;
      }}

      /* Disciplines */
      .bul-notes th:first-child, .bul-notes td:first-child {{ padding-left: 11px; }}
      .bul-notes th:last-child, .bul-notes td:last-child {{ padding-right: 11px; }}
      .bul-notes th {{
        background: var(--bul-trame);
        border-bottom: 1px solid var(--bul-filet);
        padding: 4px 7px;
        font-size: 7px; font-weight: 700;
        letter-spacing: 0.7px; text-transform: uppercase;
        color: var(--muted); text-align: right;
      }}
      .bul-notes th.bul-th-g {{ text-align: left; }}
      .bul-notes td {{
        padding: 3px 7px;
        border-bottom: 1px solid var(--bul-trame-forte);
      }}
      .bul-matiere {{ font-weight: 600; color: var(--ink); }}
      .bul-prof {{ font-size: 8px; color: var(--muted); }}
      .bul-n-fort {{ font-weight: 700; }}
      .bul-n-doux {{ color: var(--muted); }}
      .bul-appr {{ color: var(--muted); }}
      .bul-vide {{ text-align: center; color: var(--muted); padding: 14px 0; }}
      .bul-total td {{
        background: var(--bul-trame);
        font-weight: 700; color: var(--primary);
        border-top: 1px solid var(--bul-filet);
        border-bottom: none;
      }}

      /* Compartiments */
      .bul-compartiments td {{ vertical-align: top; }}
      .bul-comp {{
        padding: 6px 11px;
        border-right: 1px solid var(--bul-filet);
        width: 33.33%;
      }}
      .bul-comp-fin {{ border-right: none; }}
      .bul-comp-titre {{
        font-size: 7px; font-weight: 700; letter-spacing: 0.8px;
        text-transform: uppercase; color: var(--muted); margin-bottom: 4px;
      }}

      /* Verdict — le seul accent du document */
      .bul-verdict {{
        background: var(--bul-trame);
        border-top: 1px solid var(--bul-filet);
        border-bottom: 1px solid var(--bul-filet);
      }}
      .bul-verdict td {{ padding: 5px 11px; vertical-align: middle; }}
      .bul-verdict-cle {{ width: 42%; }}
      .bul-verdict-item {{ width: 29%; border-left: 1px solid var(--bul-filet); }}
      .bul-verdict-label {{
        font-size: 7px; font-weight: 700; letter-spacing: 0.8px;
        text-transform: uppercase; color: var(--muted);
      }}
      .bul-verdict-nombre {{
        font-family: var(--font-display);
        font-size: 26px; font-weight: 700; line-height: 1.05;
        color: var(--accent);
        font-variant-numeric: tabular-nums;
      }}
      .bul-verdict-val {{
        font-family: var(--font-display);
        font-size: 15px; font-weight: 700; color: var(--primary);
        line-height: 1.2;
      }}
      .bul-sur {{ font-size: 10px; font-weight: 400; color: var(--muted); }}

      /* Conseil */
      .bul-conseil td {{ vertical-align: top; }}
      .bul-conseil-col {{
        width: 50%; padding: 6px 11px;
        border-right: 1px solid var(--bul-filet);
      }}
      .bul-case {{ padding: 1.5px 0; color: var(--ink); }}
      .bul-carre {{
        display: inline-block; width: 8px; height: 8px;
        border: 1px solid var(--primary);
        margin-right: 7px;
      }}
      .bul-decision {{
        border-top: 1px solid var(--bul-filet);
        padding: 6px 11px;
      }}
      .bul-decision-cle {{
        font-size: 7px; font-weight: 700; letter-spacing: 0.8px;
        text-transform: uppercase; color: var(--muted); margin-right: 10px;
      }}
      .bul-decision-val {{ font-weight: 700; color: var(--primary); font-size: 10px; }}
      .bul-appreciation {{ border-top: 1px solid var(--bul-filet); padding: 6px 11px; }}
      .bul-appreciation-txt {{ margin-top: 2px; line-height: 1.45; color: var(--ink); }}

      /* Signatures */
      .bul-signatures {{ border-top: 1px solid var(--bul-filet); }}
      .bul-signatures td {{
        width: 33.33%; padding: 7px 11px 28px;
        border-right: 1px solid var(--bul-filet);
        vertical-align: top;
      }}
      .bul-sig-role {{
        font-size: 7px; font-weight: 700; letter-spacing: 0.8px;
        text-transform: uppercase; color: var(--muted);
      }}
      .bul-sig-lieu {{ margin-top: 3px; color: var(--muted); font-size: 8px; }}
    </style>
    """


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def generate_bulletin_pdf(bulletin_data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Rend le bulletin trimestriel d'un élève.

    bulletin_data : student_name, matricule, birth_date, birth_place, genre,
        photo_url, class_name, trimester, academic_year_name, average, rank,
        total_students, mention, council_decision, teacher_comment,
        subject_averages, class_stats, absences, trimester_history, reference,
        verification.
    """
    from weasyprint import HTML  # lazy import — dépendances natives GTK

    theme = PDFTheme.from_school(school_settings)
    school_name = school_settings.get("school_name") or ""
    data = dict(bulletin_data)
    data.setdefault("school_city", school_settings.get("city") or "")

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">
      {ui.base_styles(theme, page_size="A4", margin="11mm 12mm 7mm")}
      {_styles(theme)}
    </head>
    <body>
        {ui.page_decoration(theme=theme, watermark_text=school_name)}
        <div class="pdf-page-body">
        {_masthead(school_settings, data)}

        <div class="bul">
          {_band("Identité de l'élève")}
          {_identity(data)}
          {_band("Résultats par discipline")}
          {_disciplines(data.get("subject_averages") or [])}
          {_band("Synthèse du trimestre")}
          {_compartments(data)}
          {_verdict(data)}
          {_band("Conseil de classe")}
          {_mentions_conseil(data)}
          {_signatures(data)}
        </div>

        {
        ui.premium_footer(
            # Sans l'identite de l'ecole : le bloc etablissement l'annonce deja
            # en tete, nom, adresse, telephone et courriel compris. La repeter
            # au pied volait trois lignes a un document qui les compte.
            {},
            theme=theme,
            reference=bulletin_data.get("reference"),
            note="Bulletin à conserver précieusement.",
            cev_svg=(bulletin_data.get("verification") or {}).get("cev_svg"),
            seal_code=(bulletin_data.get("verification") or {}).get("seal_code"),
            verify_url=(bulletin_data.get("verification") or {}).get("verify_url"),
            manual_verify_url=(bulletin_data.get("verification") or {}).get("manual_verify_url"),
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
