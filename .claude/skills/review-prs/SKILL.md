---
name: review-prs
description: Review all open pull requests on the klassci-college-backend GitHub repo. Reads each PR's changed files, checks against project rules (Pydantic schemas aligned with frontend Zod, role values exact match, no hardcoded data, proper HTTP status codes, auth dependencies on all protected routes), then submits formal gh pr review --request-changes or --approve. Also dismisses any prior approval that should no longer stand. Use when asked to review PRs or audit open PRs.
disable-model-invocation: true
---

# Review PRs — KLASSCI Backend

Review all open PRs on `African-DC/klassci-college-backend` and submit formal GitHub reviews.

## Step 1 — Lister les PRs ouvertes

```bash
gh pr list --repo African-DC/klassci-college-backend --state open --json number,title,headRefName,author
```

## Step 2 — Pour chaque PR, lire les fichiers clés

```bash
gh pr view <N> --repo African-DC/klassci-college-backend --json files,title,headRefName
```

Fichiers prioritaires :
- `app/routers/*.py` — routes, dépendances d'auth, status codes
- `app/schemas/*.py` — Pydantic models, champs, types
- `app/models/*.py` — SQLAlchemy models, relations
- `app/core/security.py` ou `app/deps.py` — get_current_user, rôles

## Step 3 — Checklist KLASSCI Backend

### CRITIQUE (REQUEST CHANGES obligatoire si un seul est présent)

1. **Route protégée sans `Depends(get_current_user)`** — toute route non-publique doit avoir la dépendance d'auth
2. **Valeurs de `role` incorrectes** — doivent être exactement `"admin"`, `"teacher"`, `"student"`, `"parent"` (minuscules, sans accent) — le routage des portails frontend en dépend
3. **Response schema incomplet** — si le frontend a besoin de l'objet complet pour les optimistic updates, retourner l'objet entier, pas seulement `{ "id": ... }`
4. **Injection SQL** — utilisation de f-strings dans des requêtes SQLAlchemy raw
5. **Données sensibles dans les logs** — passwords, tokens loggés
6. **Migrations manquantes** — nouveau modèle sans migration Alembic correspondante

### IMPORTANT

7. **Status codes incorrects** — création → 201, non trouvé → 404, non autorisé → 401, interdit → 403
8. **Validation Pydantic manquante** — champs sans contraintes (`min_length`, `ge`, `le`) sur des inputs utilisateur
9. **N+1 queries** — relations non chargées avec `selectinload` ou `joinedload`
10. **Pas de pagination** sur les endpoints LIST (doit retourner `{ items: [...], total: N, page: N, size: N }`)

## Step 4 — Vérifier les reviews existantes et dismiss si nécessaire

```bash
gh api repos/African-DC/klassci-college-backend/pulls/<N>/reviews | node -e "
let d=''; process.stdin.on('data',c=>d+=c); process.stdin.on('end',()=>{
  const data=JSON.parse(d);
  data.forEach(r=>console.log('id='+r.id+' state='+r.state+' user='+r.user.login));
});
"
```

Dismiss une approval qui ne devrait plus tenir :
```bash
gh api repos/African-DC/klassci-college-backend/pulls/<N>/reviews/<review_id>/dismissals \
  --method PUT \
  --field message="Dismissing previous approval — <raison>. See REQUEST CHANGES review for details."
```

## Step 5 — Soumettre la review formelle

### REQUEST CHANGES
```bash
gh pr review <N> --repo African-DC/klassci-college-backend --request-changes --body "$(cat <<'EOF'
## REQUEST CHANGES — <titre PR>

### CRITIQUE

**1. <problème>** (`fichier:ligne`)
<explication + code correct>

### IMPORTANT

**...**

### Résumé

| # | Sévérité | Problème |
|---|----------|---------|
| 1 | CRITIQUE | ... |
EOF
)"
```

### APPROVE
```bash
gh pr review <N> --repo African-DC/klassci-college-backend --approve --body "LGTM — tous les critères projet sont respectés."
```

## Step 6 — Résumé final

| PR | Titre | Décision | Nb problèmes critiques |
|----|-------|----------|------------------------|
| #N | ...   | REQUEST CHANGES / APPROVE | N |

$ARGUMENTS
