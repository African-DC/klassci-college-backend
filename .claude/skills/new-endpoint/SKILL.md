---
name: new-endpoint
description: Scaffold a new FastAPI endpoint with router, schema, service, and repository following KLASSCI conventions. Use when asked to add a new API endpoint.
argument-hint: "[resource-name] e.g. enrollments"
allowed-tools: Read, Glob, Bash(python -m pytest *), Write, Edit
---

Scaffold a complete new endpoint for the resource: $ARGUMENTS

Follow this sequence exactly:

## 1. Check existing patterns
Read an existing router (e.g. `app/routers/`) to understand the current structure before creating anything.

## 2. Create the Pydantic schemas
File: `app/schemas/$ARGUMENTS.py`
- `{Resource}Create` — fields required for creation
- `{Resource}Update` — all fields optional for partial update
- `{Resource}Response` — fields returned to client (never expose password_hash, internal IDs of other tenants)

## 3. Create the SQLAlchemy model (if not exists)
File: `app/models/$ARGUMENTS.py`
- Inherit from `Base, TimestampMixin`
- All PKs are `BigInteger autoincrement`
- All FKs reference existing tables
- Add `__tablename__` and indexes

## 4. Create Alembic migration
```bash
alembic revision --autogenerate -m "add $ARGUMENTS table"
```
Then review and clean the generated migration file.

## 5. Create the repository
File: `app/repositories/{resource}_repository.py`
- `get_by_id(id)` → `T | None`
- `list(filters, page, per_page)` → `tuple[list[T], int]`
- `create(data)` → `T`
- `update(id, data)` → `T`
- `delete(id)` → `bool`

## 6. Create the service
File: `app/services/{resource}_service.py`
- Business logic only
- Calls repository for DB ops
- Calls `audit_log()` on create/update/delete
- Raises typed exceptions from `app/core/exceptions.py`

## 7. Create the router
File: `app/routers/{resource}.py`
- `GET /` — list with pagination
- `POST /` — create
- `GET /{id}` — detail
- `PUT /{id}` — update
- `DELETE /{id}` — delete
- All routes use `require_permission("{resource}:{action}")`

## 8. Register the router
Add to `app/main.py`:
```python
from app.routers import $ARGUMENTS
app.include_router($ARGUMENTS.router, prefix="/api/v1")
```

## 9. Create tests
File: `tests/routers/test_{resource}.py`
- Test each endpoint: success + main error cases
- Use async test client

## 10. Verify
```bash
python -m pytest tests/routers/test_$ARGUMENTS.py -v
```
