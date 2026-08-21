"""Ce qu'un frais donne droit : lecture, phrase, et tenue sur un reçu.

Un parent qui a payé la tenue et ne l'a pas reçue revient au secrétariat. Ces
tests portent sur la seule chose qui permet de trancher ce jour-là : la phrase
imprimée sur son reçu, et le fait qu'elle survive à une colonne vide, à une
ligne mal écrite en base, et à un budget de place très court.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models.fee import FeeEntitlementKind
from app.schemas.fee import (
    MAX_ENTITLEMENTS,
    FeeCategoryCreate,
    FeeCategoryResponse,
    FeeCategoryUpdate,
    FeeEntitlement,
)
from app.services import fee_entitlements as entitlements
from app.services.payments.receipt import _build_entitlements
from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme

TENUE = [
    {"label": "tenue de sport", "quantity": 1, "kind": "item"},
    {"label": "macarons", "quantity": 2, "kind": "item"},
    {"label": "polo", "quantity": 1, "kind": "item"},
    {"label": "infirmerie", "kind": "access"},
    {"label": "bibliothèque", "kind": "access"},
    {"label": "activités extra-scolaires", "kind": "access"},
]


def _categorie(nom: str, brut: object, description: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=nom, entitlements=brut, description=description)


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------


def test_une_categorie_sans_contrepartie_ne_promet_rien() -> None:
    assert entitlements.read(_categorie("Inscription", None)) == []


def test_une_variante_orpheline_de_categorie_ne_fait_pas_tomber_la_page() -> None:
    assert entitlements.read(None) == []


def test_une_ligne_illisible_est_ignoree_sans_emporter_les_autres() -> None:
    """Une ligne écrite à la main en base ne doit pas rendre une fiche élève 500."""
    brut = [
        {"label": "polo", "quantity": 1, "kind": "item"},
        "ceci n'est pas un objet",
        {"label": "   "},
        {"label": "infirmerie", "kind": "acces_inconnu"},
        {"label": "bibliothèque", "kind": "access"},
    ]
    lus = entitlements.read(_categorie("Tenue", brut))

    assert [e.label for e in lus] == ["polo", "bibliothèque"]


def test_une_colonne_qui_ne_contient_pas_une_liste_est_traitee_comme_vide() -> None:
    assert entitlements.read(_categorie("Tenue", {"label": "polo"})) == []


# ---------------------------------------------------------------------------
# Phrase
# ---------------------------------------------------------------------------


def test_ce_qui_se_retire_et_ce_qui_s_ouvre_sont_annonces_separement() -> None:
    texte = entitlements.summary(entitlements.read(_categorie("Tenue", TENUE)))

    assert texte.startswith("Remis : 1 tenue de sport, 2 macarons, 1 polo")
    assert "Accès : infirmerie, bibliothèque, activités extra-scolaires" in texte


def test_un_acces_ne_se_compte_pas() -> None:
    """« 1 infirmerie » n'a aucun sens ; l'absence de quantité doit se voir."""
    texte = entitlements.summary([FeeEntitlement(label="infirmerie", kind="access")])

    assert texte == "Accès : infirmerie"


def test_une_categorie_qui_ne_remet_rien_n_annonce_pas_de_remise() -> None:
    texte = entitlements.summary([FeeEntitlement(label="bibliothèque", kind="access")])

    assert "Remis" not in texte


def test_la_nature_par_defaut_est_un_objet_remis() -> None:
    assert FeeEntitlement(label="polo").kind == FeeEntitlementKind.ITEM


def test_un_libelle_vide_est_refuse() -> None:
    with pytest.raises(ValueError):
        FeeEntitlement(label="   ")


def test_un_libelle_est_debarrasse_de_ses_espaces() -> None:
    assert FeeEntitlement(label="  polo  ").label == "polo"


# ---------------------------------------------------------------------------
# Tenue dans le budget d'un reçu
# ---------------------------------------------------------------------------


def test_une_contrepartie_longue_est_coupee_sur_un_element_entier() -> None:
    """Un reçu qui annonce « 2 macaro » ne rassure personne."""
    longue = [{"label": f"article numero {i}", "quantity": 1, "kind": "item"} for i in range(15)]
    ligne = entitlements.receipt_line(entitlements.read(_categorie("Tenue", longue)))

    # +1 : le caractère de coupe s'ajoute au budget, il ne le consomme pas.
    assert len(ligne) <= entitlements.RECEIPT_LINE_BUDGET + 1
    assert ligne.endswith("…")
    dernier = ligne[:-1].rsplit(", ", 1)[-1]
    assert dernier in {f"1 article numero {i}" for i in range(15)}


def test_une_contrepartie_courte_est_rendue_entiere() -> None:
    ligne = entitlements.receipt_line(entitlements.read(_categorie("Tenue", TENUE)))

    assert not ligne.endswith("…")
    assert "activités extra-scolaires" in ligne


def test_la_description_libre_prend_le_relais_tant_que_rien_n_est_saisi() -> None:
    """Les écoles déjà en production ont écrit leur contrepartie en texte."""
    ligne = entitlements.receipt_line([], "Donne droit à :  une tenue de sport,\n deux macarons.")

    assert ligne == "Donne droit à : une tenue de sport, deux macarons."


def test_la_liste_saisie_prend_le_dessus_sur_la_description() -> None:
    ligne = entitlements.receipt_line(
        [FeeEntitlement(label="polo", quantity=1)], "vieux texte libre"
    )

    assert ligne == "Remis : 1 polo"
    assert "vieux texte" not in ligne


def test_sans_liste_ni_description_la_ligne_est_vide() -> None:
    assert entitlements.receipt_line([], None) == ""


# ---------------------------------------------------------------------------
# Composition du reçu
# ---------------------------------------------------------------------------


def _versement(noms_de_categories: list[str]) -> SimpleNamespace:
    allocations = []
    for nom in noms_de_categories:
        categorie = _categorie(nom, [{"label": f"objet {nom}", "quantity": 1, "kind": "item"}])
        allocations.append(
            SimpleNamespace(
                enrollment_fee=SimpleNamespace(
                    fee_variant=SimpleNamespace(category=categorie),
                ),
            )
        )
    return SimpleNamespace(allocations=allocations)


def test_le_recu_ne_parle_que_des_frais_regles_ce_jour() -> None:
    lignes, debordement = _build_entitlements(_versement(["Tenue"]))

    assert [nom for nom, _ in lignes] == ["Tenue"]
    assert debordement == 0


def test_une_categorie_alimentee_deux_fois_n_est_annoncee_qu_une_fois() -> None:
    """Un versement peut alimenter deux tranches du même frais."""
    lignes, _ = _build_entitlements(_versement(["Scolarité", "Scolarité"]))

    assert len(lignes) == 1


def test_au_dela_de_trois_frais_le_reste_est_compte_au_lieu_d_etre_taire() -> None:
    lignes, debordement = _build_entitlements(_versement(["A", "B", "C", "D", "E"]))

    assert len(lignes) == entitlements.RECEIPT_MAX_CATEGORIES
    assert debordement == 2


def test_un_versement_sur_un_frais_muet_n_ajoute_pas_de_ligne() -> None:
    versement = SimpleNamespace(
        allocations=[
            SimpleNamespace(
                enrollment_fee=SimpleNamespace(
                    fee_variant=SimpleNamespace(category=_categorie("Inscription", None)),
                ),
            )
        ]
    )
    lignes, debordement = _build_entitlements(versement)

    assert lignes == []
    assert debordement == 0


def test_un_versement_dont_l_inscription_a_disparu_ne_leve_pas() -> None:
    versement = SimpleNamespace(allocations=[SimpleNamespace(enrollment_fee=None)])

    assert _build_entitlements(versement) == ([], 0)


# ---------------------------------------------------------------------------
# Rendu PDF
# ---------------------------------------------------------------------------


def test_rien_a_promettre_ne_rend_pas_un_titre_suivi_du_vide() -> None:
    bloc = ui.entitlements_note([("Inscription", "")], theme=PDFTheme.from_school({}))

    assert bloc == ""


def test_le_bloc_nomme_le_frais_et_ce_qu_il_ouvre() -> None:
    bloc = ui.entitlements_note(
        [("Tenue", "Remis : 1 polo")],
        theme=PDFTheme.from_school({}),
        title="Ce que ce versement ouvre",
    )

    assert "Ce que ce versement ouvre" in bloc
    assert "Tenue" in bloc
    assert "Remis : 1 polo" in bloc


def test_le_debordement_est_annonce_au_pluriel_correct() -> None:
    theme = PDFTheme.from_school({})
    un = ui.entitlements_note([("Tenue", "Remis : 1 polo")], theme=theme, overflow=1)
    deux = ui.entitlements_note([("Tenue", "Remis : 1 polo")], theme=theme, overflow=2)

    assert "1 autre frais réglé ce jour" in un
    assert "2 autres frais réglés ce jour" in deux


def test_un_libelle_hostile_ne_sort_pas_en_html_brut() -> None:
    bloc = ui.entitlements_note(
        [("<script>", "Remis : 1 <b>polo</b>")], theme=PDFTheme.from_school({})
    )

    assert "<script>" not in bloc
    assert "<b>polo</b>" not in bloc


# ---------------------------------------------------------------------------
# Contrat API
# ---------------------------------------------------------------------------


def test_une_colonne_jamais_remplie_se_lit_comme_une_liste_vide() -> None:
    """Le champ sauvegardé mais jamais relu est le bug type de ce projet."""
    maintenant = datetime.now(UTC)
    reponse = FeeCategoryResponse.model_validate(
        SimpleNamespace(
            id=1,
            name="Inscription",
            description=None,
            entitlements=None,
            is_mandatory=True,
            priority=10,
            created_at=maintenant,
            updated_at=maintenant,
        )
    )

    assert reponse.entitlements == []


def test_une_liste_vide_efface_la_contrepartie() -> None:
    changes = FeeCategoryUpdate.model_validate({"entitlements": []}).model_dump(
        exclude_none=True, mode="json"
    )

    assert changes["entitlements"] == []


def test_renommer_une_categorie_n_efface_pas_ce_qu_elle_promet() -> None:
    changes = FeeCategoryUpdate.model_validate({"name": "Tenue scolaire"}).model_dump(
        exclude_none=True, mode="json"
    )

    assert "entitlements" not in changes


def test_la_contrepartie_part_en_base_sous_une_forme_que_json_sait_ecrire() -> None:
    """Un enum Python dans une colonne JSON casse l'écriture sans rien dire."""
    valeurs = FeeCategoryCreate.model_validate(
        {"name": "Tenue", "entitlements": [{"label": "polo", "quantity": 1, "kind": "item"}]}
    ).model_dump(mode="json")

    assert valeurs["entitlements"] == [{"label": "polo", "quantity": 1, "kind": "item"}]


def test_une_categorie_ne_peut_pas_devenir_un_inventaire() -> None:
    trop = [{"label": f"objet {i}"} for i in range(MAX_ENTITLEMENTS + 1)]
    with pytest.raises(ValueError):
        FeeCategoryCreate.model_validate({"name": "Tenue", "entitlements": trop})
