---
name: create-issue
description: Créer une issue GitHub structurée après approbation du plan. Propose l'assignation à un développeur ou au dev actuel.
---

# Créer une Issue GitHub — KLASSCI Backend

Ce skill est invoqué automatiquement après le **OKAY** du `/plan-and-confirm`.
Il crée l'issue GitHub correspondant au plan approuvé, puis propose la suite du workflow.

---

## Étape 1 — Détecter le repo actuel

```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

---

## Étape 2 — Construire et créer l'issue

À partir du plan approuvé, extraire :
- **Titre** : `type(scope): description courte` (ex: `feat(auth): JWT login endpoint`)
- **Labels** : selon le type (`feat` → `enhancement`, `fix` → `bug`, `chore` → `chore`)
- **Body** structuré :

```bash
gh issue create \
  --repo <REPO> \
  --title "<type>(<scope>): <description>" \
  --label "<label>" \
  --body "$(cat <<'EOF'
## Contexte

<!-- Pourquoi cette issue existe -->

## Ce qui sera fait

<!-- Résumé du plan approuvé -->

## Fichiers impactés

<!-- Liste des fichiers à créer/modifier -->

## Critères de succès

- [ ] <!-- critère 1 -->
- [ ] <!-- critère 2 -->

## Notes techniques

<!-- Points d'attention identifiés lors du plan -->
EOF
)"
```

Après création, afficher :
```
✅ Issue créée : #<N> — <titre>
   URL : <url>
```

---

## Étape 3 — Assignation

Demander à l'utilisateur :

> **Cette issue sera-t-elle traitée par toi ou par un autre développeur ?**
> 1. **Moi-même** → je continue directement avec `/worktree-start`
> 2. **Un autre développeur** → entre son GitHub login pour l'assigner

Si assignation à quelqu'un d'autre :
```bash
gh issue edit <N> --repo <REPO> --add-assignee <github-login>
```

Afficher :
```
✅ Issue #<N> assignée à @<login>
   Le développeur peut démarrer avec : /worktree-start <N>
```

---

## Étape 4 — Lancer le worktree (si "Moi-même")

Si l'utilisateur prend l'issue lui-même, enchaîner directement :

> Issue #<N> créée. Je lance `/worktree-start <N>` pour démarrer le travail.

Invoquer `/worktree-start` avec le numéro d'issue.

---

## Règles

- Toujours créer l'issue AVANT de toucher au code
- Le titre de l'issue = le titre de la future branche et PR
- Ne jamais créer une issue sans body structuré

$ARGUMENTS
