#!/usr/bin/env python3
"""Reset Rostan admin password then continue idempotent onboarding."""
import json
import os
import secrets
import string
import sys
import urllib.error
import urllib.request
from pathlib import Path


BASE = "http://127.0.0.1:8088/svc"
OUT = Path("/opt/apps/klassci-college/deploy/linux/.rostan-credentials.json")
ENV_PATH = Path("/opt/apps/klassci-college/deploy/linux/.env")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env


def request(method: str, path: str, *, token=None, tenant=None, body=None):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if tenant:
        headers["X-Tenant-Slug"] = tenant
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw.decode("utf-8")) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {raw}") from exc


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "R0s" + "".join(secrets.choice(alphabet) for _ in range(15)) + "!"


def login(email: str, password: str, tenant: str):
    status, payload = request("POST", "/auth/login", tenant=tenant, body={"email": email, "password": password})
    if status != 200 or not payload or "access_token" not in payload:
        raise RuntimeError(f"login failed for {email}@{tenant}: {payload}")
    return payload["access_token"], payload["user"]


def post(path, token, tenant, body):
    return request("POST", path, token=token, tenant=tenant, body=body)


def put(path, token, tenant, body):
    return request("PUT", path, token=token, tenant=tenant, body=body)


def get(path, token, tenant):
    return request("GET", path, token=token, tenant=tenant)


def find_named(items, name):
    for item in items:
        if item.get("name") == name:
            return item
    return None


def ensure_list(path, token, tenant, size=100):
    _, payload = get(f"{path}?page=1&size={size}", token, tenant)
    return payload.get("items", []) if payload else []


def reset_admin_password(password: str) -> None:
    env = load_env()
    sql = (
        "UPDATE users SET hashed_password = %s, is_active = 1, must_change_password = 0 "
        "WHERE email = 'admin@rostan-bouake.ci';"
    )
    # Hash inside backend container to stay compatible with app hasher.
    cmd = (
        "from app.core.security import hash_password; print(hash_password(%r))" % password
    )
    hashed = os.popen(
        "docker exec linux-backend-1 python -c %s" % repr(cmd)
    ).read().strip()
    if not hashed.startswith("$"):
        raise RuntimeError(f"hash failed: {hashed!r}")
    os.environ["MYSQL_PWD"] = env["MYSQL_PASSWORD"]
    import subprocess

    subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            f"MYSQL_PWD={env['MYSQL_PASSWORD']}",
            "linux-mysql-1",
            "mysql",
            "-uklassci",
            "rostan-bouake",
            "-e",
            f"UPDATE users SET hashed_password='{hashed}', is_active=1, must_change_password=0 WHERE email='admin@rostan-bouake.ci';",
        ],
        check=True,
    )


def main() -> int:
    env = load_env()
    admin_password = generate_password()
    teacher_password = generate_password()
    student_password = generate_password()
    parent_password = generate_password()

    print("== reset admin password")
    reset_admin_password(admin_password)

    print("== superadmin login")
    super_token, super_user = login(env["SUPERADMIN_EMAIL"], env["SUPERADMIN_PASSWORD"], "local")
    print("superadmin", super_user.get("role"))

    print("== admin login")
    admin_token, admin_user = login("admin@rostan-bouake.ci", admin_password, "rostan-bouake")
    print("admin", admin_user.get("role"), admin_user.get("id"))

    print("== school info")
    put(
        "/admin/settings/school-info",
        admin_token,
        "rostan-bouake",
        {
            "school_name": "College Rostan Bouake",
            "address": "Bouake, Cote d'Ivoire",
            "phone": "+2250700000001",
            "email": "contact@rostan-bouake.ci",
            "motto": "College d'excellence",
            "head_master_title": "Proviseur",
        },
    )

    years = ensure_list("/admin/academic-years", admin_token, "rostan-bouake")
    year = find_named(years, "2025-2026")
    if year is None:
        _, year = post(
            "/admin/academic-years",
            admin_token,
            "rostan-bouake",
            {"name": "2025-2026", "start_date": "2025-09-08", "end_date": "2026-06-30", "is_current": True},
        )
        print("created year", year["id"])
    else:
        print("year exists", year["id"])
    year_id = year["id"]
    if not year.get("is_current"):
        request("POST", f"/admin/academic-years/{year_id}/set-current", token=admin_token, tenant="rostan-bouake", body={})

    put(
        "/admin/settings/trimesters",
        admin_token,
        "rostan-bouake",
        {
            "trimesters": [
                {"label": "1er trimestre", "start_date": "2025-09-08", "end_date": "2025-12-19"},
                {"label": "2e trimestre", "start_date": "2026-01-05", "end_date": "2026-04-03"},
                {"label": "3e trimestre", "start_date": "2026-04-13", "end_date": "2026-06-30"},
            ]
        },
    )

    class_ids = {}
    level_ids = {}
    existing_levels = {item["name"]: item for item in ensure_list("/admin/levels", admin_token, "rostan-bouake")}
    existing_classes = {item["name"]: item for item in ensure_list("/admin/classes", admin_token, "rostan-bouake")}
    for order, name in enumerate(["6eme", "5eme", "4eme", "3eme"], start=1):
        level = existing_levels.get(name)
        if level is None:
            _, level = post("/admin/levels", admin_token, "rostan-bouake", {"name": name, "order": order})
        level_ids[name] = level["id"]
        for suffix in ("A", "B"):
            class_name = f"{name} {suffix}"
            cls = existing_classes.get(class_name)
            if cls is None:
                _, cls = post(
                    "/admin/classes",
                    admin_token,
                    "rostan-bouake",
                    {"name": class_name, "level_id": level["id"], "max_students": 40},
                )
            class_ids[class_name] = {"id": cls["id"], "level_id": level["id"]}

    _, rooms = post("/admin/rooms/batch", admin_token, "rostan-bouake", {})
    print("rooms", rooms)

    cats = {item["name"]: item for item in ensure_list("/admin/fee-categories", admin_token, "rostan-bouake")}
    if "Inscription" not in cats:
        _, cats["Inscription"] = post(
            "/admin/fee-categories",
            admin_token,
            "rostan-bouake",
            {"name": "Inscription", "description": "Frais d'inscription annuels", "is_mandatory": True},
        )
    if "Scolarite Trimestre 1" not in cats:
        _, cats["Scolarite Trimestre 1"] = post(
            "/admin/fee-categories",
            admin_token,
            "rostan-bouake",
            {"name": "Scolarite Trimestre 1", "description": "Frais de scolarite 1er trimestre", "is_mandatory": True},
        )
    variants = ensure_list("/admin/fee-variants", admin_token, "rostan-bouake")
    existing_variant_keys = {
        (v["fee_category_id"], v["level_id"], v["academic_year_id"]) for v in variants
    }
    for level_name, level_id in level_ids.items():
        for category_name, amount, desc in (
            ("Inscription", "25000", f"Inscription {level_name}"),
            ("Scolarite Trimestre 1", "75000", f"Scolarite T1 {level_name}"),
        ):
            key = (cats[category_name]["id"], level_id, year_id)
            if key in existing_variant_keys:
                continue
            post(
                "/admin/fee-variants",
                admin_token,
                "rostan-bouake",
                {
                    "fee_category_id": cats[category_name]["id"],
                    "level_id": level_id,
                    "academic_year_id": year_id,
                    "amount": amount,
                    "description": desc,
                },
            )

    teachers = ensure_list("/admin/teachers", admin_token, "rostan-bouake")
    teacher = next((t for t in teachers if t.get("first_name") == "Aissatou"), None)
    if teacher is None:
        _, teacher = post(
            "/admin/teachers",
            admin_token,
            "rostan-bouake",
            {
                "first_name": "Aissatou",
                "last_name": "Diallo",
                "email": "prof@rostan-bouake.ci",
                "password": teacher_password,
                "speciality": "Mathematiques",
                "phone": "+2250700000002",
            },
        )
    else:
        reset_user_password("prof@rostan-bouake.ci", teacher_password)

    students = ensure_list("/admin/students", admin_token, "rostan-bouake")
    student = next((s for s in students if s.get("first_name") == "Aminata"), None)
    if student is None:
        _, student = post(
            "/admin/students",
            admin_token,
            "rostan-bouake",
            {
                "first_name": "Aminata",
                "last_name": "Traore",
                "email": "eleve@rostan-bouake.ci",
                "password": student_password,
                "birth_date": "2012-03-14",
                "genre": "F",
                "city": "Bouake",
                "commune": "Air France",
            },
        )
    else:
        reset_user_password("eleve@rostan-bouake.ci", student_password)

    parents = ensure_list("/admin/parents", admin_token, "rostan-bouake")
    parent = next((p for p in parents if p.get("first_name") == "Mariam"), None)
    if parent is None:
        _, parent = post(
            "/admin/parents",
            admin_token,
            "rostan-bouake",
            {
                "first_name": "Mariam",
                "last_name": "Kone",
                "email": "parent@rostan-bouake.ci",
                "password": parent_password,
                "phone": "+2250700000003",
                "city": "Bouake",
                "commune": "Air France",
                "relationship_type": "mother",
            },
        )
    else:
        reset_user_password("parent@rostan-bouake.ci", parent_password)

    try:
        post(f"/admin/parents/{parent['id']}/link/{student['id']}", admin_token, "rostan-bouake", {})
    except RuntimeError as exc:
        if "409" not in str(exc) and "already" not in str(exc).lower() and "existe" not in str(exc).lower():
            print("link warning", exc)

    enrollments = ensure_list("/enrollments", admin_token, "rostan-bouake")
    enrollment = next((e for e in enrollments if e.get("student_id") == student["id"]), None)
    if enrollment is None:
        _, enrollment = post(
            "/enrollments",
            admin_token,
            "rostan-bouake",
            {
                "student_id": student["id"],
                "class_id": class_ids["6eme A"]["id"],
                "academic_year_id": year_id,
                "notes": "Inscription de verification prod",
            },
        )
    if enrollment.get("status") != "valide":
        request(
            "PATCH",
            f"/enrollments/{enrollment['id']}",
            token=admin_token,
            tenant="rostan-bouake",
            body={"status": "valide"},
        )

    role_checks = {}
    for email, password, expected in [
        ("admin@rostan-bouake.ci", admin_password, "admin"),
        ("prof@rostan-bouake.ci", teacher_password, "teacher"),
        ("eleve@rostan-bouake.ci", student_password, "student"),
        ("parent@rostan-bouake.ci", parent_password, "parent"),
    ]:
        token, user = login(email, password, "rostan-bouake")
        me_status, me = get("/auth/me", token, "rostan-bouake")
        role_checks[expected] = {
            "email": email,
            "login_role": user.get("role"),
            "me_role": (me or {}).get("role"),
            "me_status": me_status,
        }
        print(f"{expected}: login={user.get('role')} me={me_status}")

    dashboards = {}
    admin_tok, _ = login("admin@rostan-bouake.ci", admin_password, "rostan-bouake")
    dashboards["admin"] = get("/dashboard/stats", admin_tok, "rostan-bouake")[0]
    teacher_tok, _ = login("prof@rostan-bouake.ci", teacher_password, "rostan-bouake")
    dashboards["teacher"] = get("/teacher/dashboard", teacher_tok, "rostan-bouake")[0]
    student_tok, _ = login("eleve@rostan-bouake.ci", student_password, "rostan-bouake")
    dashboards["student"] = get("/student/dashboard", student_tok, "rostan-bouake")[0]
    parent_tok, _ = login("parent@rostan-bouake.ci", parent_password, "rostan-bouake")
    dashboards["parent"] = get("/parent/dashboard", parent_tok, "rostan-bouake")[0]
    print("dashboards", dashboards)

    creds = {
        "tenant": "rostan-bouake",
        "school": "College Rostan Bouake",
        "login_url": "http://169.58.156.206/login?c=rostan-bouake",
        "future_https": "https://college.klassci.com/login?c=rostan-bouake",
        "superadmin": {"email": env["SUPERADMIN_EMAIL"], "tenant": "local"},
        "admin": {"email": "admin@rostan-bouake.ci", "password": admin_password},
        "teacher": {"email": "prof@rostan-bouake.ci", "password": teacher_password},
        "student": {"email": "eleve@rostan-bouake.ci", "password": student_password},
        "parent": {"email": "parent@rostan-bouake.ci", "password": parent_password},
        "roles": role_checks,
        "dashboards": dashboards,
        "enrollment_id": enrollment.get("id"),
        "class": "6eme A",
    }
    OUT.write_text(json.dumps(creds, indent=2, ensure_ascii=False) + "\n")
    print("wrote", OUT)
    return 0


def reset_user_password(email: str, password: str) -> None:
    env = load_env()
    cmd = "from app.core.security import hash_password; print(hash_password(%r))" % password
    hashed = os.popen("docker exec linux-backend-1 python -c %s" % repr(cmd)).read().strip()
    if not hashed.startswith("$"):
        raise RuntimeError(f"hash failed for {email}: {hashed!r}")
    import subprocess

    subprocess.run(
        [
            "docker",
            "exec",
            "-e",
            f"MYSQL_PWD={env['MYSQL_PASSWORD']}",
            "linux-mysql-1",
            "mysql",
            "-uklassci",
            "rostan-bouake",
            "-e",
            f"UPDATE users SET hashed_password='{hashed}', is_active=1, must_change_password=0 WHERE email='{email}';",
        ],
        check=True,
    )


if __name__ == "__main__":
    sys.exit(main())
