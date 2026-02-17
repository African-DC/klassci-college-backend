---
name: worktree-finish
description: Finish work on a worktree — push branch, create PR to develop, clean up. Use when the feature/fix is complete.
allowed-tools: Bash(git *), Bash(gh *)
---

# Clôture worktree — KLASSCI Backend

## Workflow : Push → PR → Cleanup

Suis ces étapes pour finaliser le travail dans un worktree.

### Étape 1 — Vérifier l'état

```bash
git status
git diff --staged
git log --oneline origin/develop..HEAD
```

S'assurer qu'il n'y a pas de changements non commités.

### Étape 2 — Pousser la branche

```bash
git push -u origin <branch-name>
```

### Étape 3 — Créer la PR vers develop

```bash
gh pr create \
  --repo African-DC/klassci-college-backend \
  --base develop \
  --head <branch-name> \
  --title "<type>(<scope>): <description courte>" \
  --body "$(cat <<'EOF'
## Description

<!-- Ce que fait ce PR -->

## Closes

Closes #<issue-number>

## Checklist

- [ ] Tests passent (`pytest tests/ -v`)
- [ ] Linting passe (`ruff check app/ tests/`)
- [ ] Format correct (`ruff format --check app/ tests/`)
- [ ] Mypy OK (`mypy app/`)
- [ ] Branche à jour avec develop
EOF
)"
```

### Étape 4 — Afficher le lien de la PR

```bash
gh pr view --web
```

### Étape 5 — Nettoyer le worktree (après merge uniquement)

⚠️ **Ne supprimer le worktree QU'APRÈS que la PR soit mergée sur develop.**

```bash
# Depuis le repo principal (pas depuis le worktree)
git worktree remove ../worktree-<issue>-<slug>
git worktree prune
```

### Étape 6 — Confirmer à l'utilisateur

```
✅ PR créée : <URL>
   Base    : develop
   Branch  : <branch-name>
   Issue   : #<issue-number>

⏳ En attente de review.
   Une fois mergée, tu peux nettoyer avec :
   git worktree remove ../worktree-<issue>-<slug>
```

### Règles importantes

- **La PR va vers `develop`, jamais directement vers `main`**
- Le titre du PR doit suivre : `type(scope): description`
- `Closes #N` dans le body ferme l'issue automatiquement au merge
- Ne pas squash les commits (merge commit pour conserver l'historique)

$ARGUMENTS
