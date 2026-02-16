# KLASSCI Collège — Backend (FastAPI)

## Stack
- **Python** 3.12+
- **FastAPI** avec async/await partout
- **SQLAlchemy 2.0 async** (pas de SQLAlchemy synchrone)
- **Alembic** pour les migrations
- **Pydantic v2** pour la validation et les schémas
- **MySQL** (une DB par tenant)
- **Redis** pour le cache et les sessions
- **Google OR-Tools** pour la génération automatique des emplois du temps

## Architecture

```
app/
├── core/           ← config, database, security, dependencies
├── models/         ← SQLAlchemy models (un fichier par domaine)
├── schemas/        ← Pydantic schemas (request/response)
├── routers/        ← FastAPI routers (un fichier par domaine)
├── services/       ← logique métier (un service par domaine)
├── repositories/   ← accès DB (un repo par model)
└── utils/          ← helpers purs sans état
```

## Règles Absolues

### Code
- Toujours `async def` pour les endpoints et les fonctions DB
- Toujours des requêtes SQLAlchemy préparées — jamais d'interpolation SQL
- Toujours valider avec Pydantic avant toute opération DB
- Jamais de logique métier dans les routers — tout va dans les services
- Jamais de permissions hardcodées — toujours lues depuis la DB

### Sécurité
- JWT access token (15 min) + refresh token httpOnly cookie (7 jours)
- Vérifier le tenant_id sur chaque requête (middleware)
- Audit log sur toutes les mutations sensibles (paiements, notes, inscriptions)
- Jamais de secrets dans le code — toujours `.env`

### Nommage
- Fichiers : `snake_case.py`
- Classes : `PascalCase`
- Fonctions/variables : `snake_case`
- Constantes : `SCREAMING_SNAKE_CASE`
- Tables DB : `snake_case` pluriel (`enrollments`, `fee_variants`)
- Colonnes DB : `snake_case` (`created_at`, `tenant_id`)

### Tests
- Pytest + pytest-asyncio
- Un fichier de test par router : `tests/routers/test_enrollments.py`
- Factories pour les données de test (pas de fixtures statiques)
- Couvrir les happy paths + les cas d'erreur principaux

## Commandes Utiles

```bash
# Démarrage dev
uvicorn app.main:app --reload --port 8000

# Migrations
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1

# Tests
pytest tests/ -v
pytest tests/ -v --cov=app --cov-report=html

# Lint
ruff check app/
ruff format app/

# Type check
mypy app/
```

## Multi-tenant
- Le tenant est résolu depuis le sous-domaine de la requête
- Injecté dans le contexte via `TenantMiddleware`
- Chaque service reçoit `db: AsyncSession` déjà scopé sur le bon tenant
- Jamais de cross-tenant queries

## Structure des Réponses API

```python
# Succès
{"data": {...}, "message": "success"}

# Erreur
{"detail": "message d'erreur", "code": "ERROR_CODE"}

# Liste paginée
{"data": [...], "total": 100, "page": 1, "per_page": 20}
```

## Imports dans les fichiers
@rules/python.md
@rules/database.md
@rules/security.md
@rules/git.md
