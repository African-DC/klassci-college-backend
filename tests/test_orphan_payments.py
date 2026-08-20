"""Un versement survit à l'élève.

La caissière avait compté ces billets. Le tiroir était juste ce soir-là, le
point journalier a été signé, le bordereau est classé. Si supprimer un élève
effaçait ses versements, tous ces documents se mettraient à mentir en même
temps, et personne ne s'en apercevrait avant le prochain contrôle.

Ces tests tiennent les trois promesses correspondantes : le versement reste,
il s'affiche avec un nom, et les totaux de caisse ne bougent pas.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.daily_cash_book_service import _student_full_name
from app.services.payments._response import student_identity
from app.services.payments.receipt import _fee_description


def _payment(**kwargs: object) -> SimpleNamespace:
    base: dict = {
        "id": 1,
        "enrollment_id": None,
        "enrollment": None,
        "enrollment_fee": None,
        "allocations": [],
        "student_name_snapshot": "Traoré Aminata",
        "student_matricule_snapshot": "2025-6A-014",
        "amount": Decimal("50000"),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _vivant(**student_kwargs: object) -> SimpleNamespace:
    base: dict = {
        "first_name": "Aminata",
        "last_name": "Traoré",
        "enrollment_number": "2025-6A-014",
        "photo_url": "/photos/14.jpg",
    }
    base.update(student_kwargs)
    return SimpleNamespace(enrollment=SimpleNamespace(student=SimpleNamespace(**base)))


# ---------------------------------------------------------------------------
# L'identité affichée
# ---------------------------------------------------------------------------


def test_l_eleve_vivant_prime_sur_l_identite_figee() -> None:
    """Tant que la fiche existe, on montre son nom actuel : il a pu être
    corrigé depuis le versement."""
    payment = _payment(
        enrollment_id=4,
        enrollment=_vivant(last_name="Traoré-Koné").enrollment,
        student_name_snapshot="Traoré Aminata",
    )
    nom, matricule, photo, supprime = student_identity(payment)
    assert nom == "Aminata Traoré-Koné"
    assert matricule == "2025-6A-014"
    assert photo == "/photos/14.jpg"
    assert supprime is False


def test_un_versement_orphelin_porte_le_nom_fige() -> None:
    nom, matricule, _photo, supprime = student_identity(_payment())
    assert nom == "Traoré Aminata"
    assert matricule == "2025-6A-014"
    assert supprime is True


def test_un_versement_orphelin_sans_nom_fige_reste_nomme() -> None:
    """« None » sur l'écran d'une caissière ne veut rien dire."""
    nom, _matricule, _photo, _supprime = _resolve(
        _payment(student_name_snapshot=None, student_matricule_snapshot=None)
    )
    assert nom == "Élève supprimé"


def test_un_eleve_a_la_corbeille_n_est_pas_annonce_comme_supprime() -> None:
    """Deux absences distinctes qu'on ne confond pas : une fiche archivée peut
    revenir, une fiche détruite non. L'écran ne doit pas dire l'irréversible
    à la place du réversible."""
    # L'inscription est encore référencée, mais le filtre de corbeille la
    # masque : `enrollment` est None alors que `enrollment_id` ne l'est pas.
    nom, _matricule, _photo, supprime = student_identity(
        _payment(enrollment_id=4, student_name_snapshot=None)
    )
    assert supprime is False
    assert nom == "Élève archivé"


def _resolve(payment: SimpleNamespace) -> tuple[str | None, str | None, str | None, bool]:
    return student_identity(payment)


# ---------------------------------------------------------------------------
# Le bordereau journalier
# ---------------------------------------------------------------------------


def test_le_bordereau_affiche_le_nom_fige_plutot_qu_un_tiret() -> None:
    """Une colonne « Élève » remplie de tirets rendrait le document inutile au
    moment même où il sert : retrouver à qui correspondait une somme."""
    assert _student_full_name(_payment()) == "Traoré Aminata"


def test_le_bordereau_prefere_l_eleve_vivant() -> None:
    payment = _payment(enrollment_id=4, enrollment=_vivant().enrollment)
    assert _student_full_name(payment) == "Aminata Traoré"


def test_le_bordereau_retombe_sur_un_tiret_en_dernier_recours() -> None:
    assert _student_full_name(_payment(student_name_snapshot=None)) == "—"


# ---------------------------------------------------------------------------
# Le reçu
# ---------------------------------------------------------------------------


def test_le_recu_d_un_versement_orphelin_dit_la_nature_du_versement() -> None:
    """La répartition par frais est partie avec l'inscription ; le montant, lui,
    a bien été encaissé. Le reçu doit le dire au lieu de laisser un blanc."""
    assert _fee_description(_payment()) == "Versement encaissé — dossier élève supprimé"


def test_le_recu_d_un_versement_rattache_sans_allocation_reste_muet() -> None:
    """Rien n'a disparu ici : ne pas inventer un libellé qui alarmerait."""
    assert _fee_description(_payment(enrollment_id=4)) == ""


# ---------------------------------------------------------------------------
# Les totaux de caisse
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row: object = None) -> None:
        self._row = row

    def all(self) -> list:
        return []

    def scalars(self) -> "_FakeResult":
        return self

    def one_or_none(self) -> object:
        return self._row


class _CapturingDb:
    """Session factice qui retient les requêtes au lieu de les exécuter."""

    def __init__(self, row: object = None) -> None:
        self.statements: list[object] = []
        self._row = row

    async def execute(self, statement: object, *_args: object, **_kwargs: object) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult(self._row)


def _sql(statement: object) -> str:
    return str(statement).lower()


async def test_le_bordereau_et_le_point_journalier_lisent_la_meme_population() -> None:
    """Les deux documents doivent totaliser la même somme après la suppression
    d'un élève. C'est vrai tant que ni l'un ni l'autre ne joint l'inscription :
    une jointure ferait disparaître les versements orphelins d'un seul des
    deux, et deux documents signés se contrediraient."""
    from app.repositories.cash_session_repository import aggregate_date_by_cashier, aggregate_day
    from app.services.daily_cash_book_service import _load_payments_for_day

    db = _CapturingDb()
    await _load_payments_for_day(db, date(2026, 8, 20))
    await aggregate_day(db, 3, date(2026, 8, 20))
    await aggregate_date_by_cashier(db, date(2026, 8, 20))

    assert len(db.statements) == 3
    for statement in db.statements:
        assert "join enrollments" not in _sql(statement), (
            "une jointure sur l'inscription exclurait les versements orphelins"
        )


async def test_le_total_annuel_n_oublie_pas_les_versements_orphelins() -> None:
    """Une jointure interne ferait fondre le total du tableau de bord sans que
    le bordereau bouge. On rattache l'orphelin par sa date : une somme
    encaissée le 12 novembre relève de l'année qui couvre le 12 novembre."""
    from app.services.payments.query import _belongs_to_year

    db = _CapturingDb(SimpleNamespace(start_date=date(2025, 9, 1), end_date=date(2026, 7, 31)))
    condition = await _belongs_to_year(db, 2)
    rendu = _sql(condition)
    assert "enrollment_id is null" in rendu
    assert "created_at" in rendu


async def test_sans_dates_connues_on_s_en_tient_a_l_inscription() -> None:
    """Une année sans bornes ne permet aucun rattachement par date : on ne
    devine pas, on s'en tient à ce qu'on sait."""
    from app.services.payments.query import _belongs_to_year

    condition = await _belongs_to_year(_CapturingDb(), 999)
    assert "created_at" not in _sql(condition)
