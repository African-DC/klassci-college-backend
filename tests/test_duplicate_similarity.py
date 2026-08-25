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

from app.services.duplicates.similarity import (
    SEUIL_QUASI_CERTAIN,
    SEUIL_SIGNALEMENT,
    comparer,
    normaliser,
    ressemblance_date,
    ressemblance_texte,
)


def fiche(nom, prenom, naissance=None, lieu=None):
    return SimpleNamespace(last_name=nom, first_name=prenom, birth_date=naissance, birth_place=lieu)


class TestNormalisation:
    @pytest.mark.parametrize(
        ("brut", "attendu"),
        [
            ("KOUAMÉ", "kouame"),
            ("  Kouamé  ", "kouame"),
            ("MARIE-LINE", "marie line"),
            ("N'DRI", "n dri"),
            ("Aya   Marie  Adelaide", "aya marie adelaide"),
            (None, ""),
        ],
    )
    def test_les_variantes_du_guichet_se_rejoignent(self, brut, attendu):
        assert normaliser(brut) == attendu


class TestChampAbsent:
    def test_un_champ_manquant_ne_vaut_pas_desaccord(self):
        # C'est le point qui décide si le score est honnête : une fiche sans
        # lieu de naissance ne « diffère » pas, elle se tait.
        assert ressemblance_texte("Bouaké", None) is None
        assert ressemblance_date(date(2010, 5, 4), None) is None

    def test_le_score_se_renormalise_sur_les_champs_disponibles(self):
        # Deux fiches sans état civil, nom et prénom identiques : le score doit
        # être plein. S'il plafonnait à 60 % parce qu'il manque la naissance,
        # un vrai doublon passerait sous le seuil.
        r = comparer(fiche("KOUASSI", "Aya marie adelaide"), fiche("Kouassi", "AYA MARIE ADELAIDE"))
        assert r.score == pytest.approx(1.0)
        assert r.champs_compares == ("last_name", "first_name")
        assert set(r.champs_manquants) == {"birth_place", "birth_date"}

    def test_il_dit_quand_il_a_juge_sur_peu(self):
        r = comparer(fiche("TRAORE", "Siaka"), fiche("TRAORE", "Siaka"))
        assert r.juge_sur_peu is True
        complet = comparer(
            fiche("TRAORE", "Siaka", date(2008, 3, 2), "Bouaké"),
            fiche("TRAORE", "Siaka", date(2008, 3, 2), "Bouaké"),
        )
        assert complet.juge_sur_peu is False


class TestHomonymes:
    def test_un_nom_de_famille_commun_ne_suffit_pas(self):
        # Le fichier des arriérés porte trois KOUASSI et deux CAMARA dans des
        # classes différentes. Les confondre serait pire que de ne rien dire.
        r = comparer(fiche("KOUASSI", "Aya marie adelaide"), fiche("KOUASSI", "David"))
        assert r.score < SEUIL_SIGNALEMENT, f"score {r.score} : deux KOUASSI distincts signalés"

    def test_deux_camara_de_classes_differentes_restent_distincts(self):
        r = comparer(fiche("CAMARA", "Wacaltchin laetitia"), fiche("CAMARA", "Oumar yohann"))
        assert r.score < SEUIL_SIGNALEMENT

    def test_la_naissance_departage_deux_homonymes_exacts(self):
        memes = fiche("TRAORE", "Cheick moussa", date(2011, 1, 4), "Bouaké")
        autre = fiche("TRAORE", "Cheick moussa", date(2009, 8, 22), "Korhogo")
        r = comparer(memes, autre)
        assert r.score < SEUIL_QUASI_CERTAIN
        assert "birth_date" in r.champs_compares


class TestVraisDoublons:
    def test_la_casse_et_les_accents_ne_creent_pas_deux_personnes(self):
        r = comparer(
            fiche("GNOUGNOU", "Gnoleba ange david", date(2007, 6, 1), "Daloa"),
            fiche("gnougnou", "GNOLEBA ANGE DAVID", date(2007, 6, 1), "DALOA"),
        )
        assert r.quasi_certain

    def test_une_faute_de_frappe_reste_detectee(self):
        r = comparer(
            fiche("COULIBALY", "Souleymane ben junior"), fiche("COULIBALI", "Souleymane ben junior")
        )
        assert r.a_signaler, (
            f"score {r.score} : une lettre d'écart ne devrait pas masquer un doublon"
        )

    def test_jour_et_mois_intervertis_restent_suspects(self):
        # La famille dicte « 04/05 » et la saisie hésite : le cas est courant
        # et doit ressortir, sans valoir une égalité franche.
        r = ressemblance_date(date(2010, 5, 4), date(2010, 4, 5))
        assert 0.5 < r < 1.0
