"""Vérifie que les vingt et un documents de la démonstration sortent vraiment.

Un jeu de données n'est utile que si les documents qu'il alimente s'impriment.
Ce script ne suppose rien : il se connecte comme un utilisateur, appelle les
points d'entrée réels, et contrôle que la réponse est bien un PDF (elle
commence par `%PDF`) d'une taille plausible, ou un JSON non vide.

Il se lance **sur le serveur qui héberge l'application**, contre son propre
port, après le semis :

    python scripts/verify_demo_documents.py --tenant local \\
        --base-url http://localhost:8000 --email admin@klassci.com --password '...'

Les identifiants d'objets ne sont pas devinés : ils sont relus dans la base du
locataire, en lecture seule, juste avant l'appel. Un bulletin qui n'existe pas
donnerait un 404 qu'on prendrait à tort pour une régression.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Lance depuis n'importe quel dossier : `python scripts/verify_demo_documents.py`
# n'ajoute que `scripts/` au chemin d'import, jamais la racine du dépôt.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

#: Taille en dessous de laquelle un PDF est presque sûrement vide de contenu.
MIN_PDF_BYTES = 1200


@dataclass
class Probe:
    """Un document à produire, et la façon de le demander."""

    number: int
    label: str
    method: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    kind: str = "pdf"
    actor: str = "admin"
    skip_reason: str | None = None


@dataclass
class Outcome:
    probe: Probe
    status: int | str
    size: int
    detail: str


# ---------------------------------------------------------------------------
# Résolution des identifiants dans la base du locataire
# ---------------------------------------------------------------------------

_LOOKUPS: dict[str, str] = {
    "academic_year_id": "SELECT id FROM academic_years WHERE is_current = 1 LIMIT 1",
    "class_id": """
        SELECT e.class_id FROM enrollments e
        JOIN academic_years ay ON ay.id = e.academic_year_id AND ay.is_current = 1
        WHERE e.status = 'valide'
        GROUP BY e.class_id ORDER BY COUNT(*) DESC LIMIT 1
    """,
    "payment_id": "SELECT id FROM payments WHERE status = 'completed' ORDER BY id DESC LIMIT 1",
    "summons_id": "SELECT id FROM parent_summons ORDER BY id DESC LIMIT 1",
    "retake_id": "SELECT id FROM retake_authorizations ORDER BY id DESC LIMIT 1",
    "attendance_record_id": (
        "SELECT id FROM attendance_records WHERE status = 'absent' ORDER BY id DESC LIMIT 1"
    ),
    "transfer_student_id": (
        "SELECT id FROM students WHERE previous_school IS NOT NULL ORDER BY id DESC LIMIT 1"
    ),
    "documented_student_id": "SELECT student_id FROM student_documents ORDER BY id DESC LIMIT 1",
}

#: L'élève à jour de ses échéances. Le certificat de scolarité et le bulletin
#: sont retenus quand la famille a du retard : viser un bon payeur évite de
#: confondre un refus légitime (402) avec une panne.
_SETTLED_STUDENT = """
    SELECT e.student_id, e.id
    FROM enrollments e
    JOIN academic_years ay ON ay.id = e.academic_year_id AND ay.is_current = 1
    JOIN enrollment_fees ef ON ef.enrollment_id = e.id
    WHERE e.status = 'valide'
    GROUP BY e.student_id, e.id
    HAVING SUM(ef.status <> 'paid') = 0
    ORDER BY e.id LIMIT 1
"""

#: À défaut de bon payeur, n'importe quelle inscription validée fait l'affaire :
#: on passera alors par la dérogation motivée, qui est un geste réel de la
#: direction et non un contournement.
_ANY_ENROLLMENT = """
    SELECT e.student_id, e.id
    FROM enrollments e
    JOIN academic_years ay ON ay.id = e.academic_year_id AND ay.is_current = 1
    WHERE e.status = 'valide' ORDER BY e.id LIMIT 1
"""

_BULLETIN_OF = """
    SELECT b.id FROM bulletins b
    JOIN academic_years ay ON ay.id = b.academic_year_id AND ay.is_current = 1
    WHERE b.student_id = :student_id AND b.average IS NOT NULL
    ORDER BY b.trimester, b.id LIMIT 1
"""

_ANY_BULLETIN = """
    SELECT b.id FROM bulletins b
    JOIN academic_years ay ON ay.id = b.academic_year_id AND ay.is_current = 1
    WHERE b.average IS NOT NULL ORDER BY b.trimester, b.id LIMIT 1
"""

#: Une famille en retard sur son échéancier : c'est sur elle que le statut de
#: retenue dit quelque chose. Interrogé sur un bon payeur, il répondrait
#: « rien de retenu », ce qui ne prouverait pas que le calcul fonctionne.
_LATE_STUDENT = """
    SELECT e.student_id
    FROM enrollments e
    JOIN academic_years ay ON ay.id = e.academic_year_id AND ay.is_current = 1
    JOIN enrollment_fees ef ON ef.enrollment_id = e.id
    WHERE e.status = 'valide' AND ef.status <> 'paid'
    GROUP BY e.student_id ORDER BY COUNT(*) DESC LIMIT 1
"""

_CASH_DAY = """
    SELECT DATE(created_at) FROM payments
    WHERE status = 'completed' AND method = 'cash'
    GROUP BY DATE(created_at) ORDER BY COUNT(*) DESC LIMIT 1
"""

_TEACHER_EMAIL = """
    SELECT u.email FROM users u
    JOIN teacher_profiles t ON t.user_id = u.id
    WHERE u.is_active = 1 AND u.email LIKE '%%demo.klassci.ci' ORDER BY u.id LIMIT 1
"""


async def resolve_ids(tenant: str) -> dict[str, Any]:
    """Relit en base tout ce dont les appels ont besoin."""
    from app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL.format(tenant=tenant), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    found: dict[str, Any] = {}
    try:
        async with factory() as db:
            for key, query in _LOOKUPS.items():
                found[key] = (await db.execute(text(query))).scalar_one_or_none()

            row = (await db.execute(text(_SETTLED_STUDENT))).first()
            if row is None:
                row = (await db.execute(text(_ANY_ENROLLMENT))).first()
                found["needs_override"] = True
            if row is not None:
                found["student_id"], found["enrollment_id"] = int(row[0]), int(row[1])
                # Le bulletin doit être celui de cet élève-là. Un bulletin pris
                # au hasard appartiendrait à une famille en retard, et la porte
                # de paiement le retiendrait : on lirait un refus légitime
                # comme une panne de production du document.
                found["bulletin_id"] = (
                    await db.execute(text(_BULLETIN_OF), {"student_id": found["student_id"]})
                ).scalar_one_or_none()
            if not found.get("bulletin_id"):
                found["bulletin_id"] = (await db.execute(text(_ANY_BULLETIN))).scalar_one_or_none()
                found["needs_override"] = True

            found["late_student_id"] = (await db.execute(text(_LATE_STUDENT))).scalar_one_or_none()

            cash_day = (await db.execute(text(_CASH_DAY))).scalar_one_or_none()
            found["cash_date"] = str(cash_day) if cash_day else None
            found["teacher_email"] = (await db.execute(text(_TEACHER_EMAIL))).scalar_one_or_none()
    finally:
        await engine.dispose()
    return found


# ---------------------------------------------------------------------------
# Le catalogue des vingt et un documents
# ---------------------------------------------------------------------------


def build_probes(ids: dict[str, Any]) -> list[Probe]:
    """Assemble les appels, en désactivant ceux dont la donnée manque."""
    year = ids.get("academic_year_id")
    class_id = ids.get("class_id")
    student_id = ids.get("student_id")
    enrollment_id = ids.get("enrollment_id")
    override = {"override_reason": "Contrôle de production des documents avant démonstration"}
    gated = override if ids.get("needs_override") else {}

    def missing(*keys: str) -> str | None:
        absent = [key for key in keys if not ids.get(key)]
        return f"donnée absente : {', '.join(absent)}" if absent else None

    return [
        Probe(
            1,
            "Bulletin de trimestre",
            "GET",
            f"/reports/bulletins/{ids.get('bulletin_id')}/pdf",
            params=gated,
            skip_reason=missing("bulletin_id"),
        ),
        Probe(
            2,
            "Procès-verbal de conseil de classe",
            "GET",
            f"/reports/council-minutes/{class_id}/1/pdf",
            params={"academic_year_id": year},
            skip_reason=missing("class_id", "academic_year_id"),
        ),
        Probe(
            3,
            "Liste de classe",
            "GET",
            f"/admin/classes/{class_id}/roster",
            skip_reason=missing("class_id"),
        ),
        Probe(
            4,
            "Fiche d'inscription",
            "GET",
            f"/enrollments/{enrollment_id}/form",
            skip_reason=missing("enrollment_id"),
        ),
        Probe(
            5,
            "Relevé de frais d'une inscription",
            "GET",
            f"/enrollments/{enrollment_id}/statement",
            skip_reason=missing("enrollment_id"),
        ),
        Probe(
            6,
            "Reçu de versement",
            "GET",
            f"/payments/{ids.get('payment_id')}/receipt",
            skip_reason=missing("payment_id"),
        ),
        Probe(
            7,
            "Livre de caisse journalier",
            "GET",
            "/payments/daily-cash-book",
            params={"date": ids.get("cash_date")},
            skip_reason=missing("cash_date"),
        ),
        Probe(
            8,
            "Statistiques DREN (export)",
            "GET",
            f"/reports/dren-stats/{year}/export",
            params={"format": "pdf"},
            skip_reason=missing("academic_year_id"),
        ),
        Probe(
            9,
            "Rapport de fin de trimestre DEEP",
            "GET",
            f"/reports/deep-trimester/{year}",
            params={"trimester": 1},
            skip_reason=missing("academic_year_id"),
        ),
        Probe(
            10,
            "Emploi du temps (export)",
            "GET",
            "/timetable/export-pdf",
            params={"class_id": class_id},
            skip_reason=missing("class_id"),
        ),
        Probe(
            11,
            "Certificat de scolarité",
            "GET",
            f"/students/{student_id}/documents/certificat-scolarite.pdf",
            params=gated,
            skip_reason=missing("student_id"),
        ),
        Probe(
            12,
            "Attestation de fréquentation",
            "GET",
            f"/students/{student_id}/documents/attestation-frequentation.pdf",
            params=gated,
            skip_reason=missing("student_id"),
        ),
        Probe(
            13,
            "Demande de dossier scolaire",
            "GET",
            "/school-life/students/"
            f"{ids.get('transfer_student_id') or student_id}"
            "/documents/demande-dossier-scolaire.pdf",
            skip_reason=missing("student_id"),
        ),
        Probe(
            14,
            "Convocation de parent",
            "GET",
            f"/school-life/summons/{ids.get('summons_id')}/document.pdf",
            skip_reason=missing("summons_id"),
        ),
        Probe(
            15,
            "Billet d'entrée",
            "POST",
            f"/school-life/attendance-records/{ids.get('attendance_record_id')}/entry-slip.pdf",
            json_body={"notes": "Retour en classe après régularisation"},
            skip_reason=missing("attendance_record_id"),
        ),
        Probe(
            16,
            "Billet d'annulation de zéro",
            "GET",
            f"/school-life/retake-authorizations/{ids.get('retake_id')}/document.pdf",
            skip_reason=missing("retake_id"),
        ),
        Probe(17, "Performance des enseignants", "GET", "/admin/performance/teachers", kind="json"),
        Probe(18, "Performance du personnel", "GET", "/admin/performance/staff", kind="json"),
        Probe(
            19,
            "Performance vue par l'enseignant",
            "GET",
            "/teacher/performance/me",
            kind="json",
            actor="teacher",
        ),
        Probe(
            20,
            "Pièces justificatives d'une fiche élève",
            "GET",
            f"/admin/students/{ids.get('documented_student_id') or student_id}/documents",
            kind="json",
            skip_reason=missing("student_id"),
        ),
        Probe(
            21,
            "Statut de retenue d'un élève",
            "GET",
            f"/students/{ids.get('late_student_id') or student_id}/documents/release-status",
            kind="json",
            skip_reason=missing("student_id"),
        ),
    ]


# ---------------------------------------------------------------------------
# Exécution
# ---------------------------------------------------------------------------


async def login(client: httpx.AsyncClient, tenant: str, email: str, password: str) -> str | None:
    response = await client.post(
        "/auth/login",
        json={"email": email, "password": password},
        headers={"X-Tenant-Slug": tenant},
    )
    if response.status_code != 200:
        return None
    return str(response.json().get("access_token"))


def _judge(probe: Probe, response: httpx.Response) -> str:
    """Dit en une ligne si le document est présentable."""
    body = response.content
    if response.status_code != 200:
        return f"refusé : {body[:120].decode('utf-8', 'replace')}"
    if probe.kind == "pdf":
        if not body.startswith(b"%PDF"):
            return "réponse 200 mais ce n'est pas un PDF"
        if len(body) < MIN_PDF_BYTES:
            return f"PDF suspicieusement léger (< {MIN_PDF_BYTES} octets)"
        return "PDF conforme"
    payload = response.json()
    if isinstance(payload, dict) and not payload:
        return "JSON vide"
    if isinstance(payload, list) and not payload:
        return "JSON vide"
    return "JSON servi"


async def run_probes(
    base_url: str, tenant: str, tokens: dict[str, str], probes: list[Probe]
) -> list[Outcome]:
    outcomes: list[Outcome] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=180.0) as client:
        for probe in probes:
            if probe.skip_reason:
                outcomes.append(Outcome(probe, ",", 0, f"non testé : {probe.skip_reason}"))
                continue
            token = tokens.get(probe.actor)
            if not token:
                outcomes.append(
                    Outcome(probe, ",", 0, f"non testé : pas de session « {probe.actor} »")
                )
                continue

            params = {k: v for k, v in probe.params.items() if v is not None}
            try:
                response = await client.request(
                    probe.method,
                    probe.path,
                    params=params,
                    json=probe.json_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as error:
                outcomes.append(Outcome(probe, "ERR", 0, f"appel impossible : {error}"))
                continue

            outcomes.append(
                Outcome(probe, response.status_code, len(response.content), _judge(probe, response))
            )
    return outcomes


def render(outcomes: list[Outcome]) -> str:
    header = f"{'#':>2}  {'Document':44s} {'Code':>5} {'Octets':>9}  Verdict"
    lines = [header, "-" * len(header)]
    for outcome in outcomes:
        lines.append(
            f"{outcome.probe.number:>2}  {outcome.probe.label[:44]:44s} "
            f"{str(outcome.status):>5} {outcome.size:>9}  {outcome.detail}"
        )
    served = sum(1 for o in outcomes if o.status == 200)
    lines.append("-" * len(header))
    lines.append(f"{served}/{len(outcomes)} documents servis.")
    return "\n".join(lines)


async def verify(args: argparse.Namespace) -> int:
    ids = await resolve_ids(args.tenant)
    probes = build_probes(ids)

    async with httpx.AsyncClient(base_url=args.base_url, timeout=60.0) as client:
        tokens: dict[str, str] = {}
        admin_token = await login(client, args.tenant, args.email, args.password)
        if admin_token is None:
            print(f"Connexion refusée pour {args.email}.", file=sys.stderr)
            return 1
        tokens["admin"] = admin_token

        teacher_email = args.teacher_email or ids.get("teacher_email")
        if teacher_email:
            teacher_token = await login(
                client, args.tenant, str(teacher_email), args.teacher_password
            )
            if teacher_token:
                tokens["teacher"] = teacher_token

    outcomes = await run_probes(args.base_url, args.tenant, tokens, probes)
    print(render(outcomes))
    return 0 if all(o.status == 200 for o in outcomes) else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Produit les 21 documents de la démonstration")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--teacher-email", default=None)
    parser.add_argument("--teacher-password", default="Demo@2026")
    return asyncio.run(verify(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
