# API mobile — élève & parent

Contrat HTTP **backend**. Source de vérité = schémas Pydantic, pas les Zod du frontend web.

| Fichier canonique | Rôle |
|---|---|
| [`app/routers/student_portal.py`](../app/routers/student_portal.py) | Routes élève |
| [`app/schemas/student_portal.py`](../app/schemas/student_portal.py) | JSON élève |
| [`app/routers/parent_portal.py`](../app/routers/parent_portal.py) | Routes parent |
| [`app/schemas/parent_portal.py`](../app/schemas/parent_portal.py) | JSON parent |
| [`app/routers/auth.py`](../app/routers/auth.py) | Login / refresh / me |
| [`app/core/middleware.py`](../app/core/middleware.py) | Multi-tenant |

OpenAPI machine : `GET {BASE}/openapi.json` (pas de `/docs` en démo, `DEBUG=false`).

---

## Environnement démo (Windows)

| | |
|---|---|
| App web | `https://college.klassci.com` |
| API | `https://college.klassci.com/svc` |
| Health | `GET https://college.klassci.com/svc/health` → `{"status":"ok"}` |
| Préfixe | Caddy strip `/svc` → FastAPI. Toutes les routes ci-dessous sont relatives à cette base. |
| Tenant démo | slug `local` |
| Code établissement (champ login) | `LOCAL` |

Comptes (mot de passe `Admin@2026`) :

| Rôle | Email |
|---|---|
| Élève | `eleve@klassci.com` (Aminata Traoré) |
| Parent | `parent.kone@klassci.com` (Mariam Koné) |

Repos (branche `develop`) :

- Backend : https://github.com/African-DC/klassci-college-backend
- Frontend (référence UI seulement) : https://github.com/African-DC/klassci-college-frontend

---

## Multi-tenant — obligatoire

Un seul domaine pour toutes les écoles. Le tenant n’est **pas** dans l’URL.

Ordre de résolution côté serveur :

1. Claim JWT `tenant_id` (après login)
2. Header `X-Tenant-Slug` (login et refresh, **avant** JWT)
3. Sous-domaine legacy
4. Host IP / `college.klassci.com` → tenant `local`

Le body de login n’a **pas** de `school_code`. Le code établissement se transforme en slug, puis part dans le header.

```
POST /auth/login
X-Tenant-Slug: local
Content-Type: application/json

{ "email": "eleve@klassci.com", "password": "Admin@2026" }
```

| Ce que tape l’utilisateur | Header `X-Tenant-Slug` |
|---|---|
| `LOCAL` | `local` |
| `ROSTAN` | `rostan-bouake` |
| slug déjà technique (`lycee-moderne`) | le slug en minuscules |

La map d’alias (`ROSTAN` → `rostan-bouake`) vit **uniquement** dans le frontend web (`klassci-frontend/lib/utils/tenant-slug.ts`). L’app native doit la dupliquer ou envoyer le slug technique. Envoyer `X-Tenant-Slug: rostan` ouvre la mauvaise base.

Après login, le JWT porte `tenant_id` : plus besoin du header sur les GET authentifiés. Le refresh **sans** Bearer doit renvoyer `X-Tenant-Slug`.

---

## Auth

Access token : 60 min. Refresh : 7 jours, cookie httpOnly `refresh_token` — **absent du JSON**.

### `POST /auth/login`

Body : `{ "email": string, "password": string }`

Réponse :

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "email": "eleve@klassci.com",
    "role": "student",
    "first_name": "Aminata",
    "last_name": "Traoré",
    "must_change_password": false
  }
}
```

`role` ∈ `admin | staff | teacher | student | parent | super_admin`.

Natif : lire `Set-Cookie: refresh_token=...` et le stocker de façon sécurisée.

Header ensuite : `Authorization: Bearer <access_token>`.

### `POST /auth/refresh`

Pas de body. Envoyer le cookie + le slug :

```
Cookie: refresh_token=<token>
X-Tenant-Slug: local
```

Réponse : `{ "access_token": "...", "token_type": "bearer" }`. Nouveau refresh en `Set-Cookie` (rotation).

### `POST /auth/logout` → 204

### `GET /auth/me`

```json
{
  "id": 1,
  "email": "eleve@klassci.com",
  "role": "student",
  "first_name": "Aminata",
  "last_name": "Traoré",
  "tenant_id": "local",
  "is_active": true
}
```

### `POST /auth/change-password` → 204

Body : `{ "current_password": string, "new_password": string }` (`new_password` min 8). Si `must_change_password: true` au login, forcer cet écran.

Erreurs : `{ "detail": string, "code": string }` — `401 UNAUTHORIZED`, `403 PERMISSION_DENIED`, `404`, `422 VALIDATION_ERROR`.

---

## Portail élève — `GET /student/*`

Garde = profil élève lié au JWT. Pas de fiche élève → 404. Lecture seule.

| Méthode | Route | Notes |
|---|---|---|
| GET | `/student/dashboard` | Accueil |
| GET | `/student/grades?trimester=1&subject_id=3` | `trimester` 1–3, optionnel |
| GET | `/student/timetable` | EDT de la classe |
| GET | `/student/fees` | Frais + versements |
| GET | `/student/bulletins` | Publiés seulement |
| GET | `/student/bulletins/{id}/pdf` | `application/pdf` |
| GET | `/student/attendance?status=&date_from=&date_to=&page=1&size=20` | `status` : `present\|absent\|late\|excused` |
| GET | `/student/profile` | Fiche élève |

### Dashboard

```json
{
  "student_name": "Aminata Traoré",
  "class_name": "6ème A",
  "next_course": {
    "subject_name": "Mathématiques",
    "teacher_name": "Aïssatou Diallo",
    "start_time": "08:00",
    "end_time": "10:00",
    "room": "Salle 101"
  },
  "general_average": 14.25,
  "latest_grade": {
    "value": 15.5,
    "out_of": 20,
    "subject_name": "Mathématiques",
    "evaluation_title": "Devoir 1",
    "type": "devoir",
    "trimester": 1,
    "date": "2026-01-15"
  },
  "fees_remaining": 75000.0,
  "total_absences": 3,
  "current_academic_year": "2025-2026"
}
```

`next_course` et `latest_grade` peuvent être `null`. `general_average` = moyenne arithmétique brute de toutes les notes, **pas** la moyenne bulletin.

### Notes — forme réelle (liste plate)

```json
{
  "items": [
    {
      "id": 1,
      "value": "15.50",
      "status": "entered",
      "evaluation": {
        "id": 10,
        "title": "Devoir 1 Maths",
        "type": "devoir",
        "date": "2026-01-15",
        "coefficient": 2,
        "trimester": 1,
        "subject_name": "Mathématiques"
      }
    }
  ],
  "total": 1
}
```

`value` est un **Decimal JSON string**. Parser en nombre. Types d’éval : `controle | devoir | examen | oral`. Status note : `pending | entered | absent_zero | retake_pending`.

**Ne pas** attendre `{ subjects[], general_average, rank }`. Cette forme n’existe que dans le Zod web, pas sur le fil.

### Emploi du temps

```json
{
  "class_name": "6ème A",
  "slots": [
    {
      "id": 1,
      "day": "monday",
      "start_time": "08:00:00",
      "end_time": "10:00:00",
      "subject_name": "Mathématiques",
      "teacher_name": "Jean Dupont",
      "room_name": "Salle 101"
    }
  ]
}
```

`day` en anglais : `monday` … `saturday`. Heures `HH:MM:SS`.

### Frais

```json
{
  "total_due": "150000.00",
  "total_paid": "75000.00",
  "balance": "75000.00",
  "fees": [
    {
      "id": 1,
      "fee_category_name": "Scolarité T1",
      "entitlements": [{ "label": "Cahiers", "quantity": 1, "kind": "item" }],
      "amount": "150000.00",
      "status": "partial",
      "payments": [
        {
          "id": 1,
          "amount": "75000.00",
          "method": "wave",
          "status": "completed",
          "reference": "PAY-001",
          "created_at": "2026-01-10T09:00:00Z"
        }
      ]
    }
  ]
}
```

Status frais : `paid | partial | pending` (anglais). Montants en string Decimal.

### Bulletins

```json
{
  "items": [
    {
      "id": 1,
      "trimester": 1,
      "average": "14.25",
      "rank": 3,
      "mention": "B",
      "class_name": "6ème A",
      "academic_year_name": "2025-2026",
      "file_url": null,
      "generated_at": "2026-03-01T12:00:00Z",
      "is_withheld": false,
      "withheld_reason": null,
      "withheld_amount": null
    }
  ],
  "total": 1
}
```

Si `is_withheld: true` : `average`, `rank`, `mention` sont `null`. Le bulletin reste dans la liste. Afficher `withheld_reason` (montant compris). Le PDF répond **402** tant que la retenue tient. Ne pas appeler `/reports/bulletins/{id}/pdf` (droit `reports:read`, toute l’école).

### Présences

```json
{
  "items": [
    {
      "id": 1,
      "student_id": 42,
      "status": "absent",
      "time_in": null,
      "time_out": null,
      "source": "manual",
      "notes": null,
      "created_at": "2026-01-12T08:00:00Z",
      "updated_at": "2026-01-12T08:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "size": 20
}
```

### Profil

```json
{
  "id": 42,
  "first_name": "Aminata",
  "last_name": "Traoré",
  "birth_date": "2012-04-03",
  "birth_place": "Bouaké",
  "genre": "F",
  "enrollment_number": "STU-001",
  "email": "eleve@klassci.com",
  "class_name": "6ème A",
  "class_id": 3,
  "enrollment_status": "valide",
  "academic_year_name": "2025-2026"
}
```

---

## Portail parent — `GET /parent/*`

Rôle requis : `parent`. Filiation vérifiée sur chaque `{student_id}` → 403 si ce n’est pas son enfant.

| Méthode | Route |
|---|---|
| GET | `/parent/dashboard` |
| GET | `/parent/children` |
| GET | `/parent/children/{student_id}/grades?trimester=1` |
| GET | `/parent/children/{student_id}/fees` |
| GET | `/parent/children/{student_id}/bulletins` |
| GET | `/parent/children/{student_id}/bulletins/{bulletin_id}/pdf` |
| GET | `/parent/children/{student_id}/timetable` |

**Pas d’endpoint présence parent.** Absences = `total_absences` du dashboard, ou PDF attestation (ci-dessous).

### Dashboard

```json
{
  "parent_name": "Mariam Koné",
  "total_children": 1,
  "children": [
    {
      "id": 42,
      "full_name": "Aya Koné",
      "class_name": "6ème A",
      "general_average": 14.5,
      "total_absences": 2,
      "fees_remaining": 50000.0
    }
  ],
  "current_academic_year": "2025-2026"
}
```

### Liste enfants (identité, plus riche que le dashboard)

```json
{
  "children": [
    {
      "id": 42,
      "first_name": "Aya",
      "last_name": "Koné",
      "birth_date": "2012-04-03",
      "birth_place": "Bouaké",
      "enrollment_number": "STU-001",
      "relationship_type": "mother",
      "enrollment": {
        "enrollment_id": 1,
        "class_id": 3,
        "class_name": "6ème A",
        "academic_year_name": "2025-2026",
        "status": "valide"
      }
    }
  ]
}
```

`enrollment` est `null` si pas d’inscription active.

### Notes d’un enfant — liste plate

```json
{
  "student_id": 42,
  "grades": [
    {
      "id": 1,
      "value": "14.50",
      "status": "entered",
      "evaluation_title": "Devoir 1 Maths",
      "evaluation_type": "devoir",
      "evaluation_date": "2026-01-15",
      "subject_name": "Mathématiques",
      "coefficient": 2,
      "trimester": 1
    }
  ]
}
```

Pas de `child_name` / `subjects[]` / `rank` ici.

### Frais d’un enfant

```json
{
  "student_id": 42,
  "enrollment_id": 1,
  "total_due": "100000.00",
  "total_paid": "50000.00",
  "fees": [
    {
      "id": 1,
      "amount": "100000.00",
      "status": "partial",
      "category_name": "Inscription",
      "entitlements": [],
      "payments": [
        {
          "id": 1,
          "amount": "50000.00",
          "method": "wave",
          "status": "completed",
          "reference": "PAY-001",
          "created_at": "2026-01-10T09:00:00Z"
        }
      ]
    }
  ]
}
```

Pas de `child_name` / `class_name` / `balance` : calculer `total_due - total_paid`. Champ catégorie = `category_name` (pas `fee_category_name`).

### Bulletins d’un enfant

```json
{
  "student_id": 42,
  "bulletins": [
    {
      "id": 1,
      "trimester": 1,
      "average": "14.25",
      "rank": 3,
      "mention": "B",
      "class_name": "6ème A",
      "academic_year_name": "2025-2026",
      "is_published": true,
      "generated_at": "2026-03-01T12:00:00Z",
      "is_withheld": false,
      "withheld_reason": null,
      "withheld_amount": null
    }
  ]
}
```

PDF : `GET /parent/children/{student_id}/bulletins/{bulletin_id}/pdf`. Même règle de retenue (402).

### EDT d’un enfant

```json
{
  "student_id": 42,
  "class_name": "6ème A",
  "slots": [
    {
      "id": 1,
      "day": "monday",
      "start_time": "08:00",
      "end_time": "10:00",
      "subject_name": "Mathématiques",
      "teacher_name": "Jean Dupont",
      "room_name": "Salle 101"
    }
  ]
}
```

`day` anglais. Heures déjà `HH:MM` (pas `HH:MM:SS` comme l’élève).

---

## Partagé (élève et parent)

### Notifications

| Méthode | Route |
|---|---|
| GET | `/notifications?type=&read=&page=1&size=20` |
| GET | `/notifications/count` → `{ "count": 3 }` |
| PATCH | `/notifications/{id}/read` |
| POST | `/notifications/read-all` |
| POST | `/notifications/mark-seen` body `{ "notification_ids": [1, 2] }` |

Pas de push mobile. Canal in-app seulement.

### Profil self-service

| Méthode | Route |
|---|---|
| GET | `/profile/me` |
| PATCH | `/profile/me` (téléphone) |
| GET / PUT | `/profile/me/notifications` (prefs email / SMS) |

### Documents officiels PDF

Accessibles à l’élève (soi-même) et au parent (enfant lié) :

| GET | |
|---|---|
| `/students/{id}/documents/release-status` | `{ blocked, late_amount, reason, can_override }` — afficher avant le bouton |
| `/students/{id}/documents/certificat-scolarite.pdf` | Certificat de scolarité |
| `/students/{id}/documents/attestation-frequentation.pdf` | Attestation de fréquentation |

Si `blocked: true` : 402 au téléchargement. Le parent n’a pas le droit de dérogation (`can_override` false). 422 si l’enfant n’a pas d’inscription validée.

---

## Interdits / pièges

1. **Ne pas copier les Zod** `klassci-frontend/lib/contracts/*-portal.ts`. Les notes web sont un contrat inventé ; `safeValidate` y échoue. Parser Pydantic.
2. **Décimaux en string** (`"15.50"`, `"150000.00"`). `JSON.parse` ne les convertit pas.
3. **Jours EDT en anglais.** Mapper `monday` → Lundi à l’affichage.
4. **Refresh = cookie**, pas un champ JSON. Capturer `Set-Cookie`, renvoyer `Cookie` + `X-Tenant-Slug`.
5. **Code établissement ≠ slug.** `ROSTAN` n’est pas `X-Tenant-Slug: rostan`.
6. **Bulletins retenus** : liste OK, contenu vidé, PDF 402. Afficher la raison, ne pas crasher.
7. **Pas de paiement en ligne** sur ces portails. Lecture des soldes seulement.
8. **Pas d’historique de présence parent.** Dashboard ou attestation PDF.
9. **CORS** inutile en natif. Cookies `SameSite=Lax` + `Secure` hors dev.
10. Ne jamais appeler `/admin/*`, `/reports/*` (hors PDF portail), `/teacher/*` avec un compte élève/parent.

---

## Smoke démo

```
BASE=https://college.klassci.com/svc

curl -s "$BASE/health"

curl -s -D - -X POST "$BASE/auth/login" \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Slug: local" \
  -d "{\"email\":\"eleve@klassci.com\",\"password\":\"Admin@2026\"}"

# Reprendre access_token, puis :
curl -s "$BASE/student/dashboard" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/student/grades" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/student/timetable" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/student/fees" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/student/bulletins" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/student/attendance" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/student/profile" -H "Authorization: Bearer $TOKEN"
```

Même chose parent : login `parent.kone@klassci.com`, puis `/parent/dashboard` et `/parent/children`.
