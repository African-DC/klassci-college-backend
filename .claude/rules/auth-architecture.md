---
paths:
  - "app/routers/auth.py"
  - "app/core/middleware.py"
  - "app/core/security.py"
  - "app/core/dependencies.py"
  - "app/services/auth_service.py"
  - "app/schemas/auth.py"
---

# Architecture Auth — KLASSCI College (BE perspective)

## Principe

Le BE FastAPI est **l'authority de l'authentification**. Il signe les JWT, vérifie les credentials, gère les refresh tokens en cookie HttpOnly. Le FE Next.js est juste un **session manager** qui wrappe le BE via NextAuth.js v5.

**Ne pas dupliquer l'auth dans le FE.** Pas de hash bcrypt côté FE. Pas de génération JWT côté FE. Le seul rôle du FE = relayer credentials vers BE et stocker la session signée par NextAuth.

## Vue d'ensemble du flow

Voir aussi : `klassci-college-frontend/.claude/rules/auth-architecture.md` pour le schéma complet A → Z.

```
1. Browser → POST /api/auth/callback/credentials (NextAuth FE)
2. NextAuth invoke authorize() callback côté server Node
3. authorize() → fetch ${NEXT_PUBLIC_API_URL}/auth/login (server-to-BE)
4. BE FastAPI /auth/login (PRESENT RULE PORTÉE PAR CE FICHIER)
5. BE return access_token + set refresh_token cookie HttpOnly
6. NextAuth crée session cookie côté FE
7. Browser redirect vers /<role>/dashboard
8. Toutes les data fetches subséquentes carry Authorization: Bearer <access_token>
9. Chaque endpoint protégé valide le JWT via get_current_user dependency
10. TenantMiddleware injecte le tenant_id depuis le JWT pour scoper la DB
```

## Endpoints BE auth

| Endpoint | Method | Purpose | Auth required |
|---|---|---|---|
| `/auth/login` | POST | Login email+password → JWT access + refresh cookie | Non |
| `/auth/refresh` | POST | Échange refresh_token cookie contre new access_token | Non (refresh cookie) |
| `/auth/logout` | POST | Invalide la session (clear cookie) | Bearer |
| `/auth/me` | GET | Info user courant | Bearer |
| `/auth/change-password` | POST | Change password | Bearer |

**ATTENTION** : prefix actuel est `/auth/...` (PAS `/api/auth/...`). Cela peut entrer en conflit avec NextAuth qui utilise aussi `/api/auth/*` côté FE. Le routeur nginx en single-domain doit faire :
- `/api/auth/*` → :3000 (FE NextAuth handler)
- `/auth/*` → :8000 (CE BE)

OU on prefix tout le BE avec `/api/v1/` (refactor majeur, voir Pièges).

## TenantMiddleware (`app/core/middleware.py`)

Ordre de résolution du `tenant_id` (haut en bas) :

1. **JWT claim** — Si `Authorization: Bearer <token>` présent, on décode (PyJWT, signature vérifiée) et on lit `payload["tenant_id"]`. C'est l'autorité quand l'user est authentifié.
2. **Header `X-Tenant-Slug`** — Pour les requêtes avant login (ex: `/auth/login` lui-même). Le FE l'envoie quand le tenant est identifié par autre chose qu'un JWT (subdomain, code école sur login form).
3. **Subdomain extraction** — Rétrocompat multi-subdomain. `lycee-x.college.klassci.com` → tenant=`lycee-x`. Avec single-domain pivot, ce path est utilisé seulement pour les déploiements migration.
4. **Local fallback** — `localhost`, `127.0.0.1`, IP numériques → `LOCAL_TENANT_ID` (= `local`).

**Le middleware injecte `tenant_id` dans un ContextVar (`current_tenant_id`)** qui est lu par `database.py:get_tenant_db()` pour scoper la connexion SQLAlchemy au bon schéma/DB tenant.

## Pourquoi un BE séparé du FE NextAuth

NextAuth seul ne peut pas :
- Signer des JWT que le BE FastAPI peut décoder de manière fiable (les algos seraient duplicated)
- Gérer le refresh token en cookie HttpOnly côté BE (NextAuth file un cookie côté FE)
- Connaître le `tenant_id` au moment de la signature
- Vérifier le password contre la DB (NextAuth est stateless côté FE)

C'est pour ça que NextAuth est un **wrapper** : il appelle `/auth/login` sur le BE, prend la réponse, et la stocke comme session NextAuth. Le `accessToken` que le FE met dans `Authorization: Bearer` est en fait le JWT BE.

## Format des JWT BE

```
header:  { "alg": "HS256", "typ": "JWT" }
payload: {
  "sub": "1",                    # user.id
  "tenant_id": "local",          # ContextVar source
  "email": "admin@klassci.com",
  "type": "access",              # "access" or "refresh"
  "iat": 1777213700,
  "exp": 1777217300              # 15 min pour access, 7 days pour refresh
}
signature: HMAC-SHA256(SECRET_KEY, header + payload)
```

Le `SECRET_KEY` doit être identique entre instances BE (sinon JWT cross-instance refusés). En multi-instance, lire depuis le même `.env` via `app/core/config.py`.

## Permissions vs rôles

**Important** : `role` (admin/teacher/student/parent) ≠ permissions granulaires.

- `role` est dans le JWT pour le **portal routing** (admin → `/admin/*` etc.)
- Permissions sont **toujours lues depuis la DB** via `require_permission("enrollments:create")` dependency
- **Jamais** `if user.role == "admin"` hardcodé dans le code métier — voir `rules/security.md`

## Anti-patterns à bloquer en review

1. **Hashing password côté FE** — JAMAIS. Toujours envoyer le password en clair via HTTPS, le BE bcrypt hash.
2. **Lire le tenant_id depuis le body request** — JAMAIS. Toujours via le middleware (JWT signé, header validé, subdomain match RFC 1123).
3. **Pre-shared API keys pour cross-service** — utiliser le JWT signé.
4. **Hardcoder un user_id dans un endpoint** — toujours via `current_user: User = Depends(get_current_user)`.
5. **Cross-tenant query** — interdit par design. Si besoin (super-admin), utiliser le `super_admin_router` qui a une logique explicite hors `TenantMiddleware`.
6. **Renvoyer la stack trace en JSON sur erreur d'auth** — risque info disclosure. Toujours message générique + log interne.
7. **Tenant slug `..` ou `/` ou input non sanitisé dans le header X-Tenant-Slug** — `_TENANT_SLUG_RE` doit valider RFC 1123 strict.

## Pièges connus

1. **`/auth/login` PAS `/api/auth/login`** — le BE n'a pas de prefix `/api/`. Single-domain nginx doit donc router `/auth/` → :8000 EN PLUS de `/api/` → :8000 (sauf exception NextAuth).

2. **JWT expiry strict** : access_token 15 min. Si lent fetch ou retry, peut expirer mid-flight. Le FE détecte via `isTokenExpired(accessToken)` et set `error: "RefreshTokenError"` → force re-login (pas de refresh transparent en place).

3. **Refresh token cookie HttpOnly** : ne peut PAS être lu par JS. Si le browser bloque les third-party cookies (Safari ITP), le refresh cassera. Solution : same-origin via `https://college.klassci.com` (single-domain).

4. **bcrypt 4.x vs 3.x** : type stubs différents. `# type: ignore[no-any-return]` peut devenir unused selon version installée. Voir `feedback_unicode_accents.md` ligne 84.

5. **PyJWT 2.x non compatible** avec python-jose. Le repo utilise `PyJWT==2.10.1` car python-jose abandonné + CVE. Ne pas regress.

## Voir aussi

- `klassci-college-frontend/.claude/rules/auth-architecture.md` — perspective FE (NextAuth, middleware client, lib/api)
- `app/core/security.py` — `create_access_token`, `decode_jwt`
- `app/core/dependencies.py` — `get_current_user`, `TokenData`
- `app/core/middleware.py` — `TenantMiddleware`, `_resolve_tenant`
- `rules/security.md` — JWT + permissions + audit log
- CDC v2 ligne 38 — "Auth | NextAuth.js v5" + ligne 105 "user_type dans le JWT"
