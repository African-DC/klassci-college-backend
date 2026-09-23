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
| `pre-push` | push direct sur `main`/`develop`, nom de branche que la CI refusera, revue de qualité non déclarée, signature d'outil dans un commit sur le point de partir |

**Ils préviennent, ils n'imposent pas.** Un hook local s'installe volontairement
et se contourne par `--no-verify` : la CI reste le garde-fou qui compte. Leur
valeur est de dire la règle au moment où on s'en écarte, plutôt qu'en revue
trois jours plus tard — ou, pour le nom de branche, après un aller-retour de CI
et une PR à rouvrir, ce qui est déjà arrivé.

### La barrière qui ne se contourne pas

`hygiene-commits.yml` rejoue sur la pull request ce que les hooks disent en
local, là où `--no-verify` ne sert plus à rien :

| Contrôle | Ce qu'il refuse |
|---|---|
| Messages de commit | un **titre de PR** non conventionnel ou de plus de 65 caractères ; dans les commits de la branche, une signature automatique, un message non conventionnel, un sujet > 72 caractères, un `WIP` |
| Corps de la pull request | mention d'outil de génération dans la description |
| Revue de qualité déclarée | un diff qui touche du code sans ligne `Review:` dans un commit |

**Le titre compte plus que les commits.** Une fusion écrasée vers `develop`
prend pour sujet le titre de la PR, suivi de « (#NNN) ». D'où la limite à 65 :
72 moins la place du numéro. Sur les 300 derniers commits de `develop`, 78
(backend) et 83 (frontend) dépassent 72 caractères, presque tous des titres de
PR, qu'aucun hook local ne voit jamais.

**Une mise en production ne rejuge rien.** Une PR dont la tête est `develop` ou
`staging` porte des commits déjà partagés : leur défaut ne se corrige plus
qu'en réécrivant une branche protégée. Les rejuger bloquerait chaque mise en
production.

Ce contrôle manquait, et ça se voyait : deux commits du backend portent une
ligne `Co-Authored-By` que la règle interdit depuis le premier jour. Les hooks
locaux les auraient refusés ; personne ne les avait rejoués côté serveur.

Il ne lit que des messages, donc il répond en quelques secondes et ne dépend
d'aucune installation. Il ne tourne que sur pull request : signaler une fusion
après coup, quand la seule correction est de réécrire une branche partagée,
n'aide personne.

**Requis seulement une fois la protection appliquée.** Au 2026-09-22, aucune
branche n'était protégée sur les deux dépôts : l'API GitHub renvoyait 404 pour
`develop` comme pour `main`. Tant que `scripts/setup-branch-protection.sh`
(dans le dépôt backend, il couvre les deux) n'a pas été lancé, ces contrôles
s'affichent sur la PR mais n'empêchent aucune fusion.

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
