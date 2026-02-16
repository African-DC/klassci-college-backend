# app/ — Code source

Architecture en couches stricte :

```
Router → Service → Repository → Model
```

| Couche | Rôle | Règle |
|--------|------|-------|
| `routers/` | Reçoit HTTP, valide Pydantic, retourne réponse | Jamais de logique métier |
| `services/` | Logique métier, orchestration | Appelle les repositories |
| `repositories/` | Requêtes SQL uniquement | SQLAlchemy 2.0 async |
| `models/` | Définition tables MySQL | TimestampMixin sur toutes les tables |
| `schemas/` | Contrats API (Create/Update/Response) | Miroir des validations Pydantic |
| `core/` | Fondations partagées | Config, JWT, middleware, exceptions |
| `utils/` | Fonctions pures | Sans état, sans DB |
