"""Ce que le score de ressemblance doit dire, et ce qu'il ne doit pas laisser croire.

Le défaut qu'on cherche à éviter n'est pas de rater un doublon : c'est d'en
annoncer un avec assurance sur deux fiches qui n'ont qu'un nom de famille en
commun. Dans une école ivoirienne, « KOUASSI » ou « TRAORE » ne distinguent
personne, et un écran qui crie au doublon à chaque inscription finit par être
cliqué sans être lu.

Les tests appellent la vraie fonction sur des noms réels du fichier des
arriérés 2025-2026.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from app.core.names import normalize
from app.services.duplicates.similarity import (
    MATCH_THRESHOLD,
    compare,
    date_similarity,
    text_similarity,
)


def fiche(nom, prenom, naissance=None, lieu=None):
    return SimpleNamespace(last_name=nom, first_name=prenom, birth_date=naissance)


class TestNormalisation:
    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [
            ("KOUAMÉ", "kouame"),
            ("  Kouamé  ", "kouame"),
            ("MARIE-LINE", "marie line"),
            ("N'DRI", "n dri"),
            ("Aya   Marie  Adelaide", "aya marie adelaide"),
            # Les ligatures sont l'incident fondateur de ce module : une
            # fiche enregistree avec elles restait introuvable, parce que le
            # SQL les depliait et Python non. La regle n'etait gardee que par
            # un cas de parametrage dans un test de migration, qu'une purge
            # aurait emporte sans bruit.
            # Accent AU MILIEU du mot. Sans le filtre des diacritiques, le
            # depliage NFD laisse la marque combinante, que le passage
            # `isalnum` transforme en espace : « AICHA » deviendrait
            # « ai cha », donc introuvable. Aucun test ne couvrait ce cas —
            # les fiches d'essai portaient toutes leur accent en fin de mot,
            # ou l'espace produit disparait au nettoyage.
            ("AÏCHA", "aicha"),
            ("MÉLÉDJE", "meledje"),
            ("Kouaméa", "kouamea"),
            ("SŒUR ANNE", "soeur anne"),
            ("sœur anne", "soeur anne"),
            ("LÆTITIA", "laetitia"),
            ("lætitia", "laetitia"),
            (None, ""),
        ],
    )
    def test_les_variantes_du_guichet_se_rejoignent(self, brut, attendu):
        assert normalize(brut) == attendu


class TestChampAbsent:
    def test_un_prenom_vide_ne_vaut_pas_desaccord(self):
        """Deux fiches de la production ROSTAN n'ont pas de prénom.

        Elles viennent d'un état d'arriérés qui listait ces deux familles par
        leur seul nom. Si la chaîne vide comptait comme un désaccord au lieu
        d'un champ absent, le score chuterait et la famille qui revient ne
        serait pas signalée — c'est précisément celle qu'on veut rattraper,
        puisqu'elle doit encore de l'argent.
        """
        assert text_similarity("", "Aya") is None
        r = compare(fiche("TIOTE", "Mariam"), fiche("TIOTE", ""))
        assert r.score == pytest.approx(1.0)
        assert r.compared_fields == ("last_name",)
        assert r.partial_identity, "l'écran doit dire que l'état civil est incomplet"
        assert r.worth_reporting


    def test_un_champ_manquant_ne_vaut_pas_desaccord(self):
        # C'est le point qui décide si le score est honnête : une fiche sans
        # date de naissance ne « diffère » pas, elle se tait.
        assert text_similarity("Bouaké", None) is None
        assert date_similarity(date(2010, 5, 4), None) is None

    def test_le_score_se_renormalise_sur_les_champs_disponibles(self):
        # Deux fiches sans état civil, nom et prénom identiques : le score doit
        # être plein. S'il plafonnait à 60 % parce qu'il manque la naissance,
        # un vrai doublon passerait sous le seuil.
        r = compare(fiche("KOUASSI", "Aya marie adelaide"), fiche("Kouassi", "AYA MARIE ADELAIDE"))
        assert r.score == pytest.approx(1.0)
        assert r.compared_fields == ("last_name", "first_name")
        # Le lieu de naissance ne fait plus partie du calcul : à Bouaké il est
        # le même pour presque tout l'effectif.
        assert set(r.missing_fields) == {"birth_date"}

    def test_il_dit_quand_il_a_juge_sur_peu(self):
        r = compare(fiche("TRAORE", "Siaka"), fiche("TRAORE", "Siaka"))
        assert r.partial_identity is True
        complet = compare(
            fiche("TRAORE", "Siaka", date(2008, 3, 2)),
            fiche("TRAORE", "Siaka", date(2008, 3, 2)),
        )
        assert complet.partial_identity is False


class TestHomonymes:
    def test_un_nom_de_famille_commun_ne_suffit_pas(self):
        # Le fichier des arriérés porte trois KOUASSI et deux CAMARA dans des
        # classes différentes. Les confondre serait pire que de ne rien dire.
        r = compare(fiche("KOUASSI", "Aya marie adelaide"), fiche("KOUASSI", "David"))
        assert r.score < MATCH_THRESHOLD, f"score {r.score} : deux KOUASSI distincts signalés"

    def test_deux_camara_de_classes_differentes_restent_distincts(self):
        r = compare(fiche("CAMARA", "Wacaltchin laetitia"), fiche("CAMARA", "Oumar yohann"))
        assert r.score < MATCH_THRESHOLD

    def test_la_naissance_departage_deux_homonymes_exacts(self):
        memes = fiche("TRAORE", "Cheick moussa", date(2011, 1, 4))
        autre = fiche("TRAORE", "Cheick moussa", date(2009, 8, 22))
        r = compare(memes, autre)
        # Le point du test : la date FAIT baisser le score. Comparer a un seuil
        # ne le disait pas — il fallait le compare au meme couple sans dates.
        sans_dates = compare(fiche("TRAORE", "Cheick moussa"), fiche("TRAORE", "Cheick moussa"))
        assert r.score < sans_dates.score
        assert "birth_date" in r.compared_fields


class TestVraisDoublons:
    def test_la_casse_et_les_accents_ne_creent_pas_deux_personnes(self):
        r = compare(
            fiche("GNOUGNOU", "Gnoleba ange david", date(2007, 6, 1)),
            fiche("gnougnou", "GNOLEBA ANGE DAVID", date(2007, 6, 1)),
        )
        assert r.score == pytest.approx(1.0)
        assert r.worth_reporting

    def test_une_faute_de_frappe_reste_detectee(self):
        r = compare(
            fiche("COULIBALY", "Souleymane ben junior"), fiche("COULIBALI", "Souleymane ben junior")
        )
        assert r.worth_reporting, (
            f"score {r.score} : une lettre d'écart ne devrait pas masquer un doublon"
        )

    def test_jour_et_mois_intervertis_restent_suspects(self):
        # La famille dicte « 04/05 » et la saisie hésite : le cas est courant
        # et doit ressortir, sans valoir une égalité franche.
        r = date_similarity(date(2010, 5, 4), date(2010, 4, 5))
        assert 0.5 < r < 1.0


def test_la_reserve_se_leve_aussi_quand_le_prenom_manque():
    """Une fiche stockée sans prénom doit porter la réserve.

    Une version antérieure ne la levait que sur la date manquante : avec une
    date qui correspond, le score atteignait 1.0 sur le seul nom et s'affichait
    sans réserve. Les deux élèves repris sans prénom sont exactement ce cas, et
    ils doivent 101 000 FCFA à eux deux.
    """
    r = compare(
        fiche("KOUASSI", "Aya", date(2010, 3, 14)),
        fiche("KOUASSI", "", date(2010, 3, 14)),
    )
    assert r.score == pytest.approx(1.0)
    assert r.compared_fields == ("last_name", "birth_date")
    assert r.partial_identity is True
