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

## Hooks — la première ligne, pas la dernière

```bash
sh scripts/install-hooks.sh     # une fois par clone
```

`core.hooksPath` fait lire les hooks dans `.githooks/`, qui est versionné : les
règles voyagent avec le code, et une correction profite à tout le monde au
prochain `pull`.

| Hook | Ce qu'il arrête |
|---|---|
| `commit-msg` | signature automatique (`Co-Authored-By`, `Generated with`), format non conventionnel, sujet > 72 caractères, `WIP` ; avertit sur un `feat`/`fix`/`perf` sans changelog |
| `pre-commit` | commit sur `main`, fichier de secrets indexé, ruff en échec ; régénère `RELEASES.json` quand le changelog bouge |
| `pre-push` | push direct sur `main`/`develop`, nom de branche que la CI refusera |

**Ils préviennent, ils n'imposent pas.** Un hook local s'installe volontairement
et se contourne par `--no-verify` : la CI reste le garde-fou qui compte. Leur
valeur est de dire la règle au moment où on s'en écarte, plutôt qu'en revue
trois jours plus tard — ou, pour le nom de branche, après un aller-retour de CI
et une PR à rouvrir, ce qui est déjà arrivé.

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
