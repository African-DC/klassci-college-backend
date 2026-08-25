"""Seed a realistic Ivorian collège demo tenant via the deployed REST API.

Runs ON THE SERVER against http://127.0.0.1:8000 (tenant `local`).
Idempotent-ish: skips academic year / levels if they already exist.
"""
import sys
import httpx

BASE = "http://127.0.0.1:8000"
ADMIN = {"email": "admin@klassci.com", "password": "Admin@2026"}

c = httpx.Client(base_url=BASE, timeout=30.0)
errors = []


def login():
    r = c.post("/auth/login", json=ADMIN)
    r.raise_for_status()
    tok = r.json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    print("auth OK")


def _id(j):
    if isinstance(j, dict):
        return j.get("id") or j.get("data", {}).get("id")
    return None


def post(path, body, label):
    r = c.post(path, json=body)
    if r.status_code in (200, 201):
        i = _id(r.json())
        print(f"  + {label} -> id={i}")
        return i
    # tolerate "already exists" style errors
    print(f"  ! {label} -> HTTP {r.status_code}: {r.text[:160]}")
    errors.append((label, r.status_code, r.text[:200]))
    return None


def get_list(path):
    r = c.get(path)
    if r.status_code == 200:
        j = r.json()
        return j.get("items") or j.get("data") or (j if isinstance(j, list) else [])
    return []


def main():
    login()

    # 1. Academic year (reuse if a current one exists)
    print("== academic year ==")
    r = c.get("/admin/academic-years/current")
    if r.status_code == 200 and _id(r.json()):
        year_id = _id(r.json())
        print(f"  = reusing current year id={year_id}")
    else:
        year_id = post("/admin/academic-years",
                       {"name": "2025-2026", "start_date": "2025-09-01",
                        "end_date": "2026-06-30", "is_current": True}, "year 2025-2026")
    if not year_id:
        print("FATAL: no academic year"); sys.exit(1)

    # 2. Levels (reuse existing by name)
    print("== levels ==")
    existing = {l["name"]: l["id"] for l in get_list("/admin/levels") if isinstance(l, dict) and "name" in l}
    levels = {}
    for i, name in enumerate(["6ème", "5ème", "4ème", "3ème"], start=1):
        if name in existing:
            levels[name] = existing[name]; print(f"  = {name} exists id={existing[name]}")
        else:
            levels[name] = post("/admin/levels", {"name": name, "order": i}, f"level {name}")

    # 3. Classes (one A class per level)
    print("== classes ==")
    classes = {}
    for name, lvl in [("6ème A", "6ème"), ("5ème A", "5ème"), ("4ème A", "4ème"), ("3ème A", "3ème")]:
        classes[name] = post("/admin/classes",
                             {"name": name, "level_id": levels[lvl], "max_students": 40}, f"class {name}")

    # 4. Rooms (batch: one per class)
    print("== rooms (batch) ==")
    post("/admin/rooms/batch", {}, "rooms batch")

    # 5. Subjects catalogue (level_id null)
    print("== subjects catalogue ==")
    SUBJECTS = [
        ("Mathématiques", 4, 4, "#2563eb"),
        ("Français", 4, 5, "#dc2626"),
        ("Anglais", 2, 3, "#16a34a"),
        ("Histoire-Géographie", 2, 3, "#d97706"),
        ("Sciences de la Vie et de la Terre", 2, 2, "#0891b2"),
        ("Éducation Physique et Sportive", 1, 2, "#7c3aed"),
    ]
    cat = {}
    for name, coef, hrs, color in SUBJECTS:
        cat[name] = post("/admin/subjects",
                         {"name": name, "coefficient": coef, "hours_per_week": hrs, "color": color},
                         f"catalogue {name}")

    # 6. Subject instances per level (duplicate)
    print("== subject instances ==")
    inst = {}
    for lvl_name, lvl_id in levels.items():
        for name, coef, hrs, color in SUBJECTS:
            if not cat.get(name):
                continue
            iid = post("/admin/subjects/duplicate",
                       {"subject_id": cat[name], "level_id": lvl_id,
                        "coefficient": coef, "hours_per_week": hrs},
                       f"{name} / {lvl_name}")
            inst[(lvl_name, name)] = iid

    # 7. Teachers
    print("== teachers ==")
    TEACHERS = [
        ("Kouassi", "N'Dri", "kouassi.prof@college.klassci.com", "Mathématiques", "+225 07 10 20 30 40"),
        ("Aïssatou", "Diallo", "aissatou.prof@college.klassci.com", "Français", "+225 07 10 20 30 41"),
        ("Yves", "Koné", "yves.prof@college.klassci.com", "Sciences", "+225 07 10 20 30 42"),
    ]
    for fn, ln, em, spec, ph in TEACHERS:
        post("/admin/teachers",
             {"first_name": fn, "last_name": ln, "email": em, "password": "Teacher@2026",
              "speciality": spec, "phone": ph}, f"teacher {fn} {ln}")

    # 8. Students
    print("== students ==")
    STUDENTS = [
        ("Aminata", "Traoré", "aminata.eleve@college.klassci.com", "2012-05-15", "F", "COL2025001", "Cocody"),
        ("Fatou", "Sow", "fatou.eleve@college.klassci.com", "2012-03-22", "F", "COL2025002", "Treichville"),
        ("Bertrand", "Mensah", "bertrand.eleve@college.klassci.com", "2012-07-10", "M", "COL2025003", "Cocody"),
        ("Ibrahim", "Cissé", "ibrahim.eleve@college.klassci.com", "2012-01-30", "M", "COL2025004", "Yopougon"),
        ("Mariam", "Bamba", "mariam.eleve@college.klassci.com", "2012-09-05", "F", "COL2025005", "Marcory"),
    ]
    students = []
    for fn, ln, em, bd, g, num, comm in STUDENTS:
        sid = post("/admin/students",
                   {"first_name": fn, "last_name": ln, "email": em, "password": "Student@2026",
                    "birth_date": bd, "genre": g, "enrollment_number": num,
                    "city": "Abidjan", "commune": comm}, f"student {fn} {ln}")
        if sid:
            students.append(sid)

    # 9. Fee categories + variants for 6ème (for finances demo)
    print("== fee categories ==")
    FEE_CATS = [
        ("Inscription", True, 25000),
        ("Scolarité Trimestre 1", True, 50000),
        ("Scolarité Trimestre 2", True, 50000),
        ("Scolarité Trimestre 3", True, 50000),
        ("COGES", True, 10000),
        ("Tenue scolaire", False, 15000),
    ]
    print("== fee variants (6ème) ==")
    for cat_name, mand, amount in FEE_CATS:
        cid = post("/admin/fee-categories",
                   {"name": cat_name, "is_mandatory": mand}, f"feecat {cat_name}")
        if cid:
            post("/admin/fee-variants",
                 {"fee_category_id": cid, "level_id": levels["6ème"],
                  "academic_year_id": year_id, "amount": amount}, f"feevar {cat_name} {amount}")

    # 10. Enrollments (all 5 students into 6ème A)
    print("== enrollments (6ème A) ==")
    enroll_ids = []
    for sid in students:
        r = c.post("/enrollments", json={"student_id": sid, "class_id": classes["6ème A"],
                                         "academic_year_id": year_id})
        if r.status_code in (200, 201):
            eid = _id(r.json())
            enroll_ids.append(eid)
            print(f"  + enrollment student={sid} -> id={eid}")
        else:
            print(f"  ! enrollment student={sid} -> {r.status_code}: {r.text[:160]}")

    # 11. Regenerate fees for each enrollment (attach 6ème fee variants)
    print("== regenerate fees ==")
    for eid in enroll_ids:
        if eid:
            r = c.post(f"/admin/enrollments/{eid}/regenerate-fees", json={})
            print(f"  fees enrollment {eid} -> {r.status_code}")

    # 12. One demo payment (first student, 50000 cash)
    if enroll_ids and enroll_ids[0]:
        print("== demo payment ==")
        r = c.post(f"/enrollments/{enroll_ids[0]}/payments",
                   json={"amount": 50000, "method": "cash", "reference": "REC-DEMO-001"})
        print(f"  payment -> {r.status_code}: {r.text[:160]}")

    print("\n=== SUMMARY ===")
    print(f"year={year_id} levels={len(levels)} classes={len(classes)} "
          f"catalogue={sum(1 for v in cat.values() if v)} instances={sum(1 for v in inst.values() if v)} "
          f"students={len(students)} enrollments={len([e for e in enroll_ids if e])}")
    if errors:
        print(f"\n{len(errors)} non-fatal errors:")
        for lab, st, txt in errors[:20]:
            print(f"  - {lab}: {st} {txt[:120]}")
    print("SEED_DONE")


if __name__ == "__main__":
    main()
