"""Decor partage des tests de telechargement de bulletin depuis un portail.

Module d'appui, pas un module de test : il est importe par les tests de
service et par ceux de routeur, qui exercent la meme regle a deux hauteurs
differentes. Il ne remplace que deux frontieres — la fabrique de PDF, qui
exige WeasyPrint et un bulletin complet en base, et le calcul de l'echeancier
derriere la porte de paiement. Tout le reste est appele pour de vrai.
"""

from app.services import document_release_service
from app.services import parent_portal_service as parent_service
from app.services import student_portal_service as student_service
from app.services.document_release_service import ReleaseStatus

FAKE_PDF = b"%PDF-1.7 bulletin"

# Le decor : l'eleve connecte, un camarade, et leurs bulletins.
STUDENT_ID = 2
CLASSMATE_ID = 7
OWN_PUBLISHED = 5
OWN_DRAFT = 6
CLASSMATE_PUBLISHED = 9
UNKNOWN_BULLETIN = 4242

# bulletin_id -> (student_id, is_published)
BULLETINS: dict[int, tuple[int, bool]] = {
    OWN_PUBLISHED: (STUDENT_ID, True),
    OWN_DRAFT: (STUDENT_ID, False),
    CLASSMATE_PUBLISHED: (CLASSMATE_ID, True),
}


class _Result:
    """Le peu de surface que les lectures du chemin teste consomment."""

    def __init__(self, row: tuple | None) -> None:
        self._row = row

    def first(self) -> tuple | None:
        return self._row

    def scalar_one_or_none(self):
        return self._row[0] if self._row is not None else None


class BulletinsDb:
    """Une base reduite a la table des bulletins.

    Les deux requetes du chemin teste — l'appartenance, puis la resolution de
    l'eleve par la porte de paiement — ne filtrent que sur `bulletins.id` :
    l'identifiant demande se relit donc dans les parametres compiles.
    """

    def __init__(self) -> None:
        self.committed = False

    async def execute(self, stmt):
        if "bulletins" not in str(stmt):
            # `require_role` interroge la table des roles ; le decor repond
            # « parent » pour que la dependance du routeur laisse passer.
            return _Result(("parent",))
        bulletin_id = next(iter(stmt.compile().params.values()))
        return _Result(BULLETINS.get(int(bulletin_id)))

    async def get(self, _model, _pk):
        return None

    async def commit(self) -> None:
        self.committed = True


class _Student:
    def __init__(self, student_id: int) -> None:
        self.id = student_id


class _Parent:
    id = 1


def install_pdf_factory(monkeypatch) -> None:
    """La fabrique de PDF rend un document fictif : on teste l'acces, pas le rendu."""

    async def _fake_pdf(_db, _bulletin_id):
        return FAKE_PDF

    for module in (student_service, parent_service):
        monkeypatch.setattr(module.bulletin_document_service, "get_bulletin_pdf", _fake_pdf)


def open_payment_gate(monkeypatch) -> list[int]:
    """Porte de paiement ouverte. Rend la liste des eleves sur lesquels on l'interroge."""
    asked: list[int] = []

    async def _fake_evaluate(_db, student_id):
        asked.append(student_id)
        return ReleaseStatus(
            blocked=False, late_amount=0.0, enrollment_id=None, academic_year_name=None
        )

    monkeypatch.setattr(document_release_service, "evaluate_release", _fake_evaluate)
    return asked


def close_payment_gate(monkeypatch) -> None:
    """Porte de paiement fermee : la famille a des echeances en retard."""

    async def _fake_evaluate(_db, _student_id):
        return ReleaseStatus(
            blocked=True, late_amount=75000.0, enrollment_id=4, academic_year_name="2025-2026"
        )

    monkeypatch.setattr(document_release_service, "evaluate_release", _fake_evaluate)


def login_student(monkeypatch) -> None:
    """Le compte connecte pointe sur la fiche eleve `STUDENT_ID`."""

    async def _fake_student(_db, _user_id):
        return _Student(STUDENT_ID)

    monkeypatch.setattr(student_service.repo, "get_student_by_user_id", _fake_student)


def login_student_without_record(monkeypatch) -> None:
    """Le compte connecte ne pointe sur aucune fiche eleve."""

    async def _no_student(_db, _user_id):
        return None

    monkeypatch.setattr(student_service.repo, "get_student_by_user_id", _no_student)


def login_parent(monkeypatch) -> None:
    """Le compte connecte est parent de `STUDENT_ID`, et de lui seul."""

    async def _fake_parent(_db, _user_id):
        return _Parent()

    async def _fake_link(_db, _parent_id, student_id):
        return object() if student_id == STUDENT_ID else None

    monkeypatch.setattr(parent_service.repo, "get_parent_by_user_id", _fake_parent)
    monkeypatch.setattr(parent_service.repo, "get_parent_student_link", _fake_link)
