# Règles Git — KLASSCI Backend

## Format des Commits (Conventionnel)

```
<type>(<scope>): <description courte en impératif anglais>

[corps optionnel — expliquer le POURQUOI si nécessaire]
```

**Types :** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`

**Scopes backend :** `auth`, `enrollments`, `fees`, `timetable`, `grades`,
`attendance`, `notifications`, `permissions`, `tenant`, `migrations`

**Règles :**
- Description ≤ 72 caractères
- Impératif anglais : "add" pas "added", "fix" pas "fixed"
- PAS de "Generated with Claude Code" ni "Co-Authored-By"
- PAS de commits WIP sur develop/main

**Exemples corrects :**
```
feat(enrollments): add enrollment status transition validation
fix(auth): prevent cross-tenant token reuse
feat(timetable): implement OR-Tools automatic schedule generation
perf(grades): add index on evaluations.class_id for faster queries
test(fees): add fee variant matrix calculation tests
```

## Branches

```
main        ← production (protégée)
staging     ← recette
develop     ← intégration (base de toutes les features)
feature/*   ← feature/enrollment-workflow
fix/*       ← fix/jwt-tenant-validation
hotfix/*    ← hotfix/payment-duplicate-charge
```

**Règle :** Toujours brancher depuis `develop`, jamais depuis `main`.

## Pull Requests

- Titre = message du commit principal
- Description : contexte + ce qui a changé + comment tester
- 1 reviewer minimum obligatoire
- CI doit passer (lint + tests) avant merge autorisé
- Squash merge vers develop
- Supprimer la branche après merge

## Ce Qu'on Ne Fait JAMAIS

```bash
# INTERDIT — push direct sur main/develop
git push origin main

# INTERDIT — force push sur branches partagées
git push --force origin develop

# INTERDIT — commit les secrets
git add .env

# INTERDIT — gros commits fourre-tout
git commit -m "fix stuff and add things and update deps"
```
