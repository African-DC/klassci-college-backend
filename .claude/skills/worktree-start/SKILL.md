---
name: worktree-start
description: Start work on a GitHub issue using a git worktree. Use when starting a new feature or fix from an issue number.
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

### Étape 5 — Proposer le serveur de développement

Après création du worktree, proposer :

> Veux-tu que je lance le serveur de développement dans le worktree ?
> ```bash
> cd ../worktree-<issue>-<slug>
> uvicorn app.main:app --reload --port 8000
> ```
> Ou tu le lances toi-même ?

Attendre la validation fonctionnelle avant de passer à la PR.

### Règles importantes

- **Jamais travailler directement sur `develop` ou `main`**
- Le worktree est un dossier séparé — chaque dev peut en avoir plusieurs en parallèle
- Toujours partir de `origin/develop` (pas du local)
- Branche naming : `feature/N-desc`, `fix/N-desc`, `hotfix/N-desc`, `chore/desc`
- Une fois le travail terminé dans le worktree, invoquer `/worktree-finish`

$ARGUMENTS
