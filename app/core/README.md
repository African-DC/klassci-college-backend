# app/core/ — Fondations

Fichiers partagés par toute l'application.

| Fichier | Contenu |
|---------|---------|
| `config.py` | Settings Pydantic (lit `.env`) |
| `database.py` | Moteur SQLAlchemy async + sessions |
| `security.py` | JWT encode/decode, hash passwords |
| `dependencies.py` | `get_current_user`, `get_tenant_db`, `require_permission` |
| `middleware.py` | `TenantMiddleware` — résout le tenant depuis le sous-domaine |
| `exceptions.py` | Exceptions typées (`NotFoundError`, `PermissionError`...) |
| `audit.py` | Fonction `audit_log()` — obligatoire sur toutes les mutations sensibles |

## Règle critique

Le `TenantMiddleware` résout le tenant depuis le sous-domaine à chaque requête.
La session DB (`get_tenant_db`) est scopée sur la base du tenant courant.
Jamais de cross-tenant data access.
