# Règle Changelog — KLASSCI College Backend

Le fichier `CHANGELOG.md` à la racine documente les évolutions de la
plateforme du **point de vue de l'utilisateur final** (admin, enseignant,
parent, élève, devops). Il suit
[Keep a Changelog 1.1.0](https://keepachangelog.com/fr/1.1.0/) et
[Semantic Versioning](https://semver.org/lang/fr/).

## Quand alimenter

| Type de commit                | Action sur le changelog |
|-------------------------------|--------------------------|
| `feat:` qui change l'API ou le comportement perceptible | **Oui** → `Added` ou `Changed` |
| `fix:` d'un bug que l'utilisateur a vu               | **Oui** → `Fixed`              |
| `perf:` ressenti côté usage                          | **Oui** → `Changed`            |
| `refactor:` qui modifie un endpoint ou un contrat    | **Oui** → `Changed`            |
| Faille corrigée, dépendance bumpée pour un CVE       | **Oui** → `Security`           |
| `chore:` / `docs:` / `test:` / `ci:` / `style:`      | **Non** — n'a rien à faire dans le changelog |

> **Règle d'or** : si la ligne ne dit pas *« ce que l'utilisateur peut
> faire de plus, mieux, ou différemment »*, elle ne devrait pas être là.

## Comment écrire une entrée

1. **Perspective utilisateur, pas développeur.**
   - ❌ « Added `EnrollmentService` class with `create()` method »
   - ✅ « Inscription multi-étape avec validation automatique des frais
     selon le niveau et la série *(admin)* »

2. **Français propre, accents corrects.** Cohérence avec le reste du
   projet : voir `marcel-global-preferences.md`.

3. **Persona en italique** à la fin de la ligne :
   `*(admin)*`, `*(enseignant)*`, `*(parent)*`, `*(élève)*`,
   `*(super-admin)*`, `*(devops)*`. Plusieurs si pertinent : `*(admin,
   enseignant)*`. **Pas de persona** si vraiment transverse.

4. **Lien PR** quand identifiable : `(#42)` à la fin.

5. **Une ligne, ≤ 25 mots.** Si le sujet déborde, c'est qu'il devrait
   être deux entrées séparées.

6. **Pas de jargon technique** : aucune mention de classes Python, de
   modules `app/...`, de noms de migrations, de libs (FastAPI, SQLAlchemy,
   Alembic). On décrit *ce que ça fait*, pas *avec quoi*.

## Où l'ajouter

Toujours sous `## [Unreleased]` au sommet du fichier, dans la section
appropriée. Si la section n'existe pas encore dans `Unreleased`, la
créer dans cet ordre canonique (sauter celles vides) :

```
### Added
### Changed
### Deprecated
### Removed
### Fixed
### Security
```

## Quand bumper la version

| De            | À             | Critère                                                 |
|---------------|---------------|---------------------------------------------------------|
| `0.1.0-alpha` | `0.1.0`       | Première école pilote tournée 30 jours sans incident P0 |
| `0.1.x`       | `0.2.0`       | Nouvelle capacité majeure (ex : Wave/Orange Money live) |
| `0.x.y`       | `1.0.0`       | 5 écoles en production payante, SLA tenu 60 jours       |
| `X.Y.Z`       | `X.Y.(Z+1)`   | Patch — fix bugs sans nouvelle capacité                 |
| `X.Y.Z`       | `X.(Y+1).0`   | Minor — nouvelle capacité, rétrocompatible              |
| `X.Y.Z`       | `(X+1).0.0`   | Major — breaking change (migration manuelle requise)    |

À chaque release :

1. Renommer `## [Unreleased]` en `## [X.Y.Z] - YYYY-MM-DD` (date du tag).
2. Recréer un bloc `## [Unreleased]` vide au sommet.
3. Ajouter / mettre à jour les liens compare en bas du fichier :
   ```
   [unreleased]: https://github.com/African-DC/klassci-college-backend/compare/vX.Y.Z...HEAD
   [X.Y.Z]: https://github.com/African-DC/klassci-college-backend/compare/vX.Y.W...vX.Y.Z
   ```
4. Tagger : `git tag vX.Y.Z` puis `git push --tags`.

## Garde-fou CI

Le workflow `.github/workflows/changelog-check.yml` tourne sur chaque pull
request. Il :

1. Détecte les commits `feat`/`fix`/`perf`/`breaking` depuis la base.
2. **Échoue** si un de ces commits est présent ET que `CHANGELOG.md`
   n'apparaît pas dans le diff de la PR.
3. Affiche la liste des commits incriminés dans le job log.

Pour contourner volontairement (changement vraiment interne, refactor pur,
réorganisation docs) : appliquer le label `skip-changelog` sur la PR. Le
workflow se met alors en pass automatique. Reviewer peut le retirer pour
forcer une mise à jour si besoin.

**Comme avec toute règle automatique, ce check ne valide pas la qualité
éditoriale**. Il garantit qu'une ligne a été ajoutée — ne dispense pas de
suivre les principes plus haut (perspective utilisateur, persona italique,
français propre, méga-grouping).

## Anti-patterns à bloquer en revue

1. Entrée qui décrit l'implémentation : `Added EnrollmentRepository.create_batch`
2. Entrée qui mentionne un fichier ou un module : `routers/grades.py`
3. Entrée qui ne dit pas *quoi*, juste *pourquoi internal* : `Refactor for cleaner code`
4. Section `## [Unreleased]` absente ou vide bloquée à plusieurs commits feat
5. Version sans date, ou date au format autre qu'ISO 8601 (`YYYY-MM-DD`)
6. Sections vides laissées dans le fichier (les supprimer)
7. Mélange français / anglais dans les entrées
8. Lister 5 commits CRUD distincts au lieu de méga-grouper en une feature

## Exemples corrects

```markdown
### Added
- Saisie de notes en mode dictée vocale, parfait pour les enseignants qui
  préfèrent réciter les notes plutôt que taper *(enseignant)* (#40)
- Provisioning d'un nouvel établissement en une commande CLI : DB, rôles,
  admin, e-mail de bienvenue *(super-admin)* (#40)

### Fixed
- Saisie d'absence enregistrait l'élève comme « non saisi » au lieu de
  « absent » dans certains cas *(enseignant)* (#73)

### Security
- Token de rafraîchissement déplacé en cookie HttpOnly Secure SameSite,
  l'access token JWT reste 15 minutes pour limiter l'exposition (#52)
```

## Voir aussi

- `klassci-college-frontend/.claude/rules/changelog.md` — règle équivalente
  côté FE (entrées séparées dans le CHANGELOG.md du frontend)
- `klassci-backend/CHANGELOG.md` — fichier alimenté
- Rule `rules/git.md` — formats de commit qui alimentent les sections
