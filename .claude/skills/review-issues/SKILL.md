---
name: review-issues
description: Review all open issues on klassci-college-backend and klassci-college-frontend. Cross-links BE and FE issues, adds Pydantic schema alignment specs, verifies role values match frontend expectations, and edits the GitHub issues with enriched content. Use when asked to review, enrich, or cross-link issues between the backend and frontend repos.
disable-model-invocation: true
---

# Review Issues — KLASSCI (BE + FE)

Enrich and cross-link all open issues across both repos. Mirror de `review-issues` côté frontend, centré sur les contraintes backend.

## Step 1 — Lister les issues dans les deux repos

```bash
gh issue list --repo African-DC/klassci-college-backend --state open --json number,title,labels
gh issue list --repo African-DC/klassci-college-frontend --state open --json number,title,labels
```

## Step 2 — Matrice de correspondance BE ↔ FE

Identifier les paires :
- Auth BE → Auth FE
- Endpoints CRUD BE → Hooks TanStack FE
- Schemas Pydantic BE → Schemas Zod FE
- Contrats API → Issue dédiée dans les deux repos

## Step 3 — Enrichir chaque issue BE avec

### Alignement schéma Pydantic ↔ Zod
```markdown
## Alignement Schéma

**Pydantic Response (ce repo) :**
```python
class <Resource>Response(BaseModel):
    id: int
    field1: str
    created_at: datetime
```

**Zod Frontend attendu (African-DC/klassci-college-frontend) :**
```ts
export const <resource>Schema = z.object({
  id: z.number(),
  field1: z.string(),
  created_at: z.string().datetime(),
})
```
```

### Contrainte critique sur `role`
```markdown
## Contrainte role — CRITIQUE

Les valeurs de `role` retournées par l'API d'authentification DOIVENT être :
`"admin"` | `"teacher"` | `"student"` | `"parent"`

Minuscules, sans accents, sans espaces. Le routage des portails frontend (`middleware.ts`) fait un `===` strict sur ces valeurs.
```

### Contrat API
```markdown
## Contrat API

| Méthode | Endpoint | Status OK | Auth |
|---------|----------|-----------|------|
| POST | `/api/v1/<resource>` | 201 | Bearer |
| GET | `/api/v1/<resource>` | 200 | Bearer |
| GET | `/api/v1/<resource>/{id}` | 200 | Bearer |
| PATCH | `/api/v1/<resource>/{id}` | 200 | Bearer |
| DELETE | `/api/v1/<resource>/{id}` | 204 | Bearer |

**IMPORTANT :** Les endpoints POST/PATCH doivent retourner l'objet complet (pas seulement `{ id }`), car le frontend utilise l'optimistic update reconciliation.
```

### Cross-link FE
```markdown
## Lié au frontend

African-DC/klassci-college-frontend#<N>
```

## Step 4 — Appliquer les éditions

```bash
gh issue view <N> --repo African-DC/klassci-college-backend --json body
gh issue edit <N> --repo African-DC/klassci-college-backend --body "$(cat <<'EOF'
<contenu_existant_conservé>

## Alignement Schéma
...

## Contrat API
...

## Lié au frontend
African-DC/klassci-college-frontend#<N>
EOF
)"
```

## Step 5 — Résumé final

| Repo | Issue | Enrichissement ajouté |
|------|-------|----------------------|
| BE | #N - titre | Pydantic schema + contrat API + cross-link FE#N |
| FE | #N - titre | Zod schema + optimistic updates + cross-link BE#N |

$ARGUMENTS
