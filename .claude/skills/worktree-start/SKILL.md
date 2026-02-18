---
name: worktree-start
description: Start work on a GitHub issue using a git worktree. Use when starting a new feature or fix from an issue number.
allowed-tools: Bash(git *), Bash(gh *)
---

# Démarrage worktree — KLASSCI Backend

## Workflow : Issue → Worktree → Branch → PR

Suis ces étapes pour démarrer le travail sur une issue GitHub.

### Étape 1 — Récupérer les infos de l'issue

```bash
gh issue view $ISSUE_NUMBER --repo African-DC/klassci-college-backend
```

Extraire :
- Le **titre** de l'issue pour nommer la branche
- Le **type** : feat / fix / refactor / test / chore

### Étape 2 — Mettre à jour develop en local

```bash
git fetch origin
git checkout develop
git pull origin develop
```

### Étape 3 — Créer le worktree

Format du dossier : `../worktree-<issue>-<slug>`
Format de la branche : `<type>/<issue>-<slug-du-titre>`

Exemple pour l'issue #1 "feat(core): bootstrap FastAPI" :
- Dossier : `../worktree-1-core-bootstrap`
- Branche : `feature/1-core-bootstrap`

```bash
git worktree add ../worktree-<issue>-<slug> -b <type>/<issue>-<slug> origin/develop
```

### Étape 4 — Confirmer à l'utilisateur

Afficher :
```
✅ Worktree créé :
   Dossier : ../worktree-<issue>-<slug>
   Branche : <type>/<issue>-<slug>
   Base    : origin/develop

Ouvre ce dossier dans ton éditeur ou navigue avec :
  cd ../worktree-<issue>-<slug>
```

### Règles importantes

- **Jamais travailler directement sur `develop` ou `main`**
- Le worktree est un dossier séparé — chaque dev peut en avoir plusieurs en parallèle
- Toujours partir de `origin/develop` (pas du local)
- Branche naming : `feature/N-desc`, `fix/N-desc`, `hotfix/N-desc`, `chore/desc`

$ARGUMENTS
