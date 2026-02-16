# app/schemas/ — Schémas Pydantic

Un fichier par domaine. Trois schémas minimum par entité.

## Convention

```python
class EnrollmentCreate(BaseModel):    # Recu pour créer
class EnrollmentUpdate(BaseModel):    # Recu pour modifier (tous champs optionnels)
class EnrollmentResponse(BaseModel):  # Retourné au client
    model_config = ConfigDict(from_attributes=True)
```

## Règle de sécurité

Ne jamais exposer dans `Response` : `password_hash`, données financières cross-tenant.

## Schémas partagés

Créer `common.py` avec :
- `PaginatedResponse[T]` — `{"data": [...], "total": N, "page": N, "per_page": N}`
- `DataResponse[T]` — `{"data": {...}}`
- `ErrorResponse` — `{"detail": "...", "code": "..."}`
