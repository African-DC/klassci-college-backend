# KLASSCI Collège — Backend

API REST multi-tenant pour la gestion scolaire des établissements secondaires ivoiriens.
Construit avec **FastAPI + SQLAlchemy 2.0 async + MySQL**.

## Stack

| Technologie | Usage | Version |
|-------------|-------|---------|
| FastAPI | Framework API | 0.115+ |
| SQLAlchemy 2.0 | ORM async | 2.x |
| Alembic | Migrations DB | 1.x |
| Pydantic v2 | Validation / Schemas | 2.x |
| MySQL 8 | Base de données (1 DB / tenant) | 8.x |
| Redis | Cache + sessions + blacklist JWT | 7.x |
| Celery | Tâches async (PDF, OR-Tools, emails) | 5.x |
| passlib + bcrypt | Hash des mots de passe | - |
| python-jose | JWT tokens | - |
| pydantic-settings | Configuration via .env | - |

## Architecture

```
app/
├── core/           ← config, database, security, dependencies, middleware, exceptions, audit
├── models/         ← SQLAlchemy models (1 fichier par entité)
├── schemas/        ← Pydantic schemas Create/Update/Response (1 fichier par domaine)
├── routers/        ← FastAPI routers (1 fichier par domaine)
├── services/       ← Logique métier (1 service par domaine)
├── repositories/   ← Accès BDD SQLAlchemy async (1 repo par entité)
└── utils/          ← Helpers purs (timetable_generator, pdf_client, sms...)
alembic/            ← Migrations versionnées
tests/              ← pytest (structure miroir de app/)
```

Chaque dossier contient un `README.md` qui explique ce qu'il faut créer.

## Multi-tenant

```
app.klassci.com  →  login central (détecte le tenant par email)
    ↓
college-{slug}.klassci.com  →  app tenant
    ↓
MySQL: klassci_{slug}  →  base isolée par école
```

Le JWT contient `tenant_id`. Le `TenantMiddleware` extrait le subdomain et vérifie
la cohérence à chaque requête.

## Setup local

```bash
git clone https://github.com/African-DC/klassci-college-backend.git
cd klassci-college-backend
git checkout develop

# Python 3.12+
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt

# Variables d'environnement
cp .env.example .env
# Remplir DATABASE_URL, REDIS_URL, SECRET_KEY dans .env

# Appliquer les migrations
alembic upgrade head

# Lancer le serveur de développement
uvicorn app.main:app --reload --port 8000
```

API disponible sur http://localhost:8000
Documentation Swagger : http://localhost:8000/docs

## Variables d'environnement requises (`.env`)

```env
DATABASE_URL=mysql+aiomysql://user:pass@localhost:3306/klassci_master
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=change-this-to-a-long-random-string-min-32-chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ENVIRONMENT=development

# DigitalOcean Spaces (stockage fichiers / PDF bulletins)
DO_SPACES_KEY=your_key
DO_SPACES_SECRET=your_secret
DO_SPACES_BUCKET=klassci-dev
DO_SPACES_REGION=fra1

# Twilio (SMS / WhatsApp notifications)
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
```

## Commandes utiles

```bash
# Tests
pytest                                          # Tous les tests
pytest tests/test_auth.py -v                   # Un fichier spécifique
pytest --cov=app --cov-report=term-missing      # Avec coverage

# Qualité de code
ruff check app/                                # Linter
ruff format app/                               # Formateur
mypy app/                                      # Type checking

# Migrations
alembic revision --autogenerate -m "description"  # Nouvelle migration
alembic upgrade head                              # Appliquer
alembic downgrade -1                             # Revenir d'une migration
alembic current                                  # État actuel
```

## Claude Code Skills disponibles

Dans VS Code avec Claude Code :

| Commande | Action |
|----------|--------|
| `/run-tests` | ruff + mypy + pytest avec coverage |
| `/new-endpoint` | Scaffold complet (schema → repo → service → router → tests) |
| `/new-migration` | Workflow guidé Alembic |
| `/commit` | Commit conventionnel guidé |
| `/create-pr` | PR vers develop avec template |
| `/code-review` | Vérification sécurité + qualité avant PR |

## Workflow Git

```
main      ← Production (PR uniquement, 1 reviewer minimum)
staging   ← Pré-production (PR uniquement)
develop   ← Intégration (PR uniquement)
feature/* ← Votre branche de travail
```

```bash
git checkout develop && git pull origin develop
git checkout -b feature/ma-feature
# ... développer ...
git add app/specific/file.py
git commit -m "feat(scope): description"
git push origin feature/ma-feature
gh pr create --base develop
```

## Issues GitHub — Ordre de développement

1. [#1 feat(core): bootstrap FastAPI](https://github.com/African-DC/klassci-college-backend/issues/1) — **Commencer ici**
2. [#2 feat(db): schema MySQL complet](https://github.com/African-DC/klassci-college-backend/issues/2)
3. [#3 feat(auth): authentification JWT](https://github.com/African-DC/klassci-college-backend/issues/3)
4. [#4 feat(enrollments): CRUD inscriptions](https://github.com/African-DC/klassci-college-backend/issues/4)
5. [#5 feat(timetable): emploi du temps + OR-Tools](https://github.com/African-DC/klassci-college-backend/issues/5)
6. [#6 feat(grades): notes + bulletins PDF](https://github.com/African-DC/klassci-college-backend/issues/6)

## Conventions de code

- **Toujours async** — `async def` + `await` partout, zéro appel SQLAlchemy synchrone
- **Jamais de permissions hardcodées** — toujours `require_permission("resource", "action")`
- **Toujours Pydantic** pour la validation — jamais valider manuellement les inputs
- **Toujours audit log** sur les mutations sensibles (enrollments, payments, roles...)
- **Typage strict** — mypy sans erreur avant chaque PR
- **Requêtes préparées** — SQLAlchemy génère les requêtes, jamais de SQL brut avec f-strings

## Format des réponses API

```json
// Liste
{ "data": [...], "total": 150, "page": 1, "per_page": 20 }

// Objet unique
{ "data": { ... } }

// Erreur validation (422)
{ "detail": [{ "field": "email", "message": "Email invalide" }] }

// Erreur métier (400/403/404)
{ "detail": "Message d'erreur" }
```
