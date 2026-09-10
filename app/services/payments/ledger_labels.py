"""Les mots du point par catégorie : ses colonnes, ses états, ses mentions.

Le PDF et le classeur sortent du même `CategoryLedger` et se lisent côte à
côte : le comptable recalcule dans le tableur ce que le PDF fait signer. Ils
portaient pourtant chacun leur propre table d'états, leurs propres colonnes et
leurs propres phrases — et les mots avaient déjà divergé. Le pied du PDF disait
« les impayés n'y figurent pas », celui du classeur « les impayés ne peuvent
pas y figurer » ; le PDF annonçait des « Dépôts en nature », le classeur du
« Déposé en nature ». Deux vérités selon le fichier qu'on ouvre, sur un
document qui sert à justifier un virement.

C'est la raison qui a réuni ici les phrases du journal des versements
(`journal_labels`), et c'est la même ici. Le contrat HTTP continue, lui, de
transporter la CLÉ — jamais le libellé.

## La règle du tiret, qui vaut pour les deux sorties

Un tiret dit « on ne sait pas », jamais « zéro ». Un montant nul s'écrit donc
« 0 F » des deux côtés : le PDF écrivait « — » sous une ligne soldée pendant
que le classeur écrivait « 0 F », et le même élève sortait « inconnu » dans
l'un et « soldé » dans l'autre.

Et une colonne dont personne ne peut connaître la valeur ne se remplit pas de
tirets : elle est ABSENTE. C'est pourquoi `colonnes()` décide des colonnes
plutôt que de laisser chaque sortie dresser sa liste.

Fonctions pures, sans base de données : elles se lisent et se testent seules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.services.pdf._helpers import format_xof

#: Ce qu'on écrit quand la donnée n'existe pas — jamais à la place d'un zéro.
ABSENT = "—"

#: Le mot de chaque état, du point de vue de qui lit CE document-ci.
#:
#: Volontairement distinct de `theme.STATUS_LABELS_FR` : sur un frais on dit
#: « Soldé » et « Dû », là où le vocabulaire des versements dit « Payé » et
#: « En attente ». Distinct, mais écrit une seule fois : les deux sorties
#: portaient la même table en double, et une table en double finit toujours
#: par diverger.
ETATS: dict[str, str] = {
    "paid": "Soldé",
    "partial": "Partiel",
    "pending": "Dû",
    "in_kind": "Déposé en nature",
    "waived": "Exonéré",
}

#: Le pseudo-seau de la liste d'appel, qui n'est l'état d'aucune ligne. Sa clé
#: est celle de `fee_category_ledger.SEAU_IMPAYES`, où les seaux se décident ;
#: ici on ne fait que la nommer.
SEAUX: dict[str, str] = {
    "impayes": "Impayés (aucun versement et partiels)",
}

#: L'étiquette du gros montant, et la ligne de total qui doit lui répondre.
#: Elle dit QUELS versements sont comptés : un total qui ne le dit pas laisse
#: croire que les versements saisis mais non encaissés en font partie.
VERSEMENTS_COMPTES = "versements validés"
TOTAL_LABEL = "Total entré sur la période"

#: Ce que porte un tableau vide, des deux côtés. Le classeur n'écrivait rien
#: du tout : un tableau sans ligne et sans phrase se lit comme un export raté.
AUCUNE_LIGNE = "Aucune inscription ne porte ce frais sur ce périmètre."

#: La ligne la plus importante d'un document de guichet : sans elle, il se lit
#: comme le compte de l'école entière.
AVERTISSEMENT_CAISSE = (
    "Ce document ne couvre que votre caisse. Il dit ce que vous avez encaissé "
    "sur ce frais, et rien de ce qui a été encaissé ailleurs. Le reste à payer "
    "n'y figure donc pas : le calculer sur une seule caisse annoncerait une "
    "dette chez des familles ayant payé à un autre guichet."
)

#: Le même rappel, en pied, pour qui feuillette par la fin.
RAPPEL_CAISSE = "Document limité à votre caisse — les impayés n'y figurent pas."

#: Ce que le document conserve quand il couvre toutes les caisses.
RAPPEL_ECOLE = "À conserver pour la comptabilité de l'établissement."


@dataclass(frozen=True, slots=True)
class Colonne:
    """Une colonne du détail par élève, telle que les deux sorties la rendent."""

    key: str
    label: str
    #: Vrai quand la cellule porte un montant : le classeur l'écrit alors en
    #: nombre — pour qu'on puisse en refaire la somme — et le PDF l'aligne à
    #: droite.
    money: bool = False


def colonnes(*, consolide: bool, accepts_in_kind: bool) -> tuple[Colonne, ...]:
    """Les colonnes du détail, décidées une fois pour les deux sorties.

    Deux d'entre elles ne sont pas toujours là, et leur absence est le message.

    - **Reste à payer** ne se calcule que sur tout l'argent reçu. Sans ce
      droit, la colonne sortait intégralement textuelle — des tirets sur toutes
      les lignes — sous un en-tête qui promettait des francs. Une colonne qu'on
      ne peut pas remplir se retire ; elle ne se remplit pas de tirets.
    - **Déposé le** n'a de sens que sur une catégorie qui accepte les dépôts en
      nature. Le classeur la portait, le PDF non : le même document ne montrait
      pas les mêmes colonnes selon le fichier qu'on ouvrait.
    """
    liste = [
        Colonne("eleve", "Élève"),
        Colonne("matricule", "Matricule"),
        Colonne("classe", "Classe"),
        Colonne("etat", "État"),
        Colonne("du", "Dû (XOF)", money=True),
        Colonne("entre", "Entré sur la période (XOF)", money=True),
    ]
    if consolide:
        liste.append(Colonne("reste", "Reste à payer (XOF)", money=True))
    if accepts_in_kind:
        liste.append(Colonne("depose", "Déposé le"))
    return tuple(liste)


def etat_label(status: str) -> str:
    """Le mot d'un état de ligne. Un état inconnu s'imprime tel quel.

    Le replier sur « Autre » le rendrait invisible ; imprimé brut, il se
    remarque et se corrige.
    """
    return ETATS.get(status, status)


def seau_label(state: str) -> str:
    """Le mot du seau demandé — un pseudo-seau, ou l'état qu'il réunit."""
    return SEAUX.get(state) or etat_label(state)


def period_label(date_from: datetime | None, date_to: datetime | None) -> str:
    """Décrit la période couverte, telle qu'elle a été appliquée.

    « Depuis le début de l'année » plutôt que « Toutes périodes » comme le
    journal : ce document-ci est borné par une année scolaire, qui est un
    paramètre obligatoire de son entrée.
    """
    if date_from is not None and date_to is not None:
        return f"Du {date_from:%d/%m/%Y} au {date_to:%d/%m/%Y}"
    if date_from is not None:
        return f"À partir du {date_from:%d/%m/%Y}"
    if date_to is not None:
        return f"Jusqu'au {date_to:%d/%m/%Y}"
    return "Depuis le début de l'année"


def filters_label(*, state: str | None, q: str | None) -> str:
    """Énumère les filtres de liste appliqués, ou renvoie une chaîne vide.

    Lus du filtre, jamais reconstitués depuis les données rendues : une liste
    vide ne dit rien du seau qui l'a vidée. Une chaîne vide se lit « aucun
    filtre », ce qui est exact — annoncer un filtre qui n'a pas porté ferait
    mentir le document autant que le taire.
    """
    parts: list[str] = []
    if state:
        parts.append(f"État : {seau_label(state)}")
    if q:
        parts.append(f"Recherche : « {q} »")
    return " · ".join(parts)


def issued_label(issued_at: datetime, issued_by: str | None) -> str:
    """« Édité le 04/09/2026 à 14:32 par N'GUESSAN Marcel ».

    Sans nom connu, on n'annonce pas d'auteur : « par — » se lit comme un champ
    cassé. La date, elle, ne manque jamais — le classeur ne la portait pas du
    tout, et deux tirages du même écran à deux jours d'écart étaient
    indiscernables une fois imprimés.
    """
    quand = f"Édité le {issued_at:%d/%m/%Y à %H:%M}"
    if issued_by and issued_by.strip() not in ("", ABSENT, "-"):
        return f"{quand} par {issued_by}"
    return quand


def entre_label(eleves: int) -> str:
    """L'étiquette du montant entré, et quels versements y sont comptés."""
    return (
        f"Entré en argent sur la période ({VERSEMENTS_COMPTES}) — "
        f"{eleves} élève{'s' if eleves > 1 else ''}"
    )


def entre_meta(eleves: int, total: Decimal) -> str:
    """La même étiquette, suivie de son montant : l'en-tête du classeur."""
    return f"{entre_label(eleves)}, {format_xof(total)} F"


def reste_du_label(eleves: int, total: Decimal) -> str:
    """Ce qui reste dû, et le fait que la période n'y change rien."""
    return (
        f"Reste à payer aujourd'hui : {format_xof(total)} F · "
        f"{eleves} élève{'s' if eleves > 1 else ''}. "
        "Un état, pas un événement : il ne dépend pas de la période choisie."
    )


def depots_label(depots: int) -> str:
    """Le compte des dépôts, et ce qu'un dépôt vaut.

    L'application enregistre un dépôt PAR LIGNE DE FRAIS, jamais une quantité.
    Parler de paquets promettrait un décompte que la base ne tient pas, et
    c'est sur cette promesse qu'on commanderait une livraison.
    """
    return (
        f"Déposé en nature sur la période : {depots} dépôt{'s' if depots > 1 else ''}. "
        "Un dépôt vaut une ligne de frais remise, jamais une quantité d'articles."
    )


def troncature_label(affichees: int, retenues: int) -> str:
    """Avertit quand le document ne couvre pas tout ce que le périmètre a trouvé.

    Un document tronqué qui se tait vaut moins qu'un document absent : on le
    signe en croyant qu'il est complet.
    """
    return (
        f"Ce document ne présente que {affichees} ligne{'s' if affichees > 1 else ''} "
        f"sur les {retenues} du périmètre. Resserrez la classe ou la période "
        "pour obtenir un document complet."
    )
