# Rule : Pas de `from __future__ import annotations` dans un router avec endpoints 204

## Quand s'active

Cette rule s'active automatiquement quand :
- Tu crées ou modifies un fichier dans `app/routers/` qui contient un endpoint avec `status_code=204` ou `status_code=status.HTTP_204_NO_CONTENT`
- Tu ajoutes `from __future__ import annotations` au début d'un router existant
- Tu ajoutes un endpoint 204 (typiquement DELETE) dans un router qui a déjà `from __future__ import annotations`

## La règle

**Un router FastAPI ne doit JAMAIS combiner :**

```python
from __future__ import annotations  # PEP 563 — stringifie toutes les annotations
```

**ET un endpoint :**

```python
@router.delete("/x", status_code=status.HTTP_204_NO_CONTENT)
async def del_x(...) -> None: ...   # ← le `-> None` est le piège
```

Le router crash **à l'import du module** avec :

```
AssertionError: Status code 204 must not have a response body
```

## Pourquoi cette rule existe

**Incident fondateur 2026-05-20** (PR #150) — `teacher_attendance.py` ajouté en
Phase 7b BE foundation (PR #146) combinait `from __future__ import annotations`
et un DELETE 204 avec `-> None`. Le router ne se chargeait pas, mais le bug
était masqué par une cascade CI :

1. `Lint & Type Check` failait (drift ruff 0.8.4 CI vs 0.15.12 local)
2. `Tests` était `skipped` à cause du fail lint
3. `Alembic migrations idempotence` était `skipped` à cause du fail lint
4. Bug d'import jamais déclenché en CI
5. Bug 0030 chain `down_revision = "0029_school_pdf_customization"` (au lieu de
   `"0029"`) jamais déclenché non plus

Coût : **toute provision d'un nouveau tenant échouait**, tout deploy EC2 qui
exécute `alembic upgrade head` échouait. Découvert seulement quand la PR #150
a bumpé ruff et que les tests ont enfin tourné.

## Pourquoi techniquement

Sous PEP 563 (`from __future__ import annotations`), toutes les annotations
sont stringifiées au parse. FastAPI 0.115.6 inspecte ensuite l'annotation de
retour pour déterminer le `response_model`. Sur un endpoint avec
`status_code=204` :

- Sans PEP 563 : `-> None` est résolu en `NoneType`, FastAPI sait qu'il n'y a
  pas de body → OK
- Avec PEP 563 : `-> None` est la string `"None"`, FastAPI ne résout pas
  correctement et infère un response_model truthy → assertion violée

Python 3.12 (la version du projet) supporte déjà nativement PEP 604
(`int | None`, `str | None`) et le `from __future__ import annotations` n'est
**plus nécessaire** pour les unions modernes. Donc on peut juste le retirer.

## Pattern correct

### Option A — Retirer le future import (recommandé)

```python
# app/routers/teacher_attendance.py
"""Router pointage enseignant."""

# PAS d'import `from __future__ import annotations`
from datetime import date as date_type
from fastapi import APIRouter, Depends, Query, status
# ...

@router.delete(
    "/teacher-attendance/{attendance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_attendance(
    attendance_id: int,
    # ...
) -> None:
    """OK — le -> None est résolu en NoneType, pas en string."""
    await service.delete_attendance(...)
```

Si le router contient des unions ou generics modernes, Python 3.12 les supporte
nativement :

```python
# Pas besoin de PEP 563 pour ça :
async def list_x(
    page: int = 1,
    status_filter: str | None = None,
    date_from: date | None = None,
) -> dict[str, Any]: ...
```

### Option B — Garder PEP 563 mais retirer `-> None`

Si pour une raison X le router doit garder `from __future__ import annotations`
(typiquement parce qu'il y a beaucoup de forward references) :

```python
# Ne PAS annoter le retour des endpoints 204
@router.delete("/x", status_code=status.HTTP_204_NO_CONTENT)
async def del_x(...):  # pas de `-> None`
    await service.delete(...)
```

Moins clean (l'annotation de retour disparaît du contrat), donc préférer
l'Option A.

## Reproducer minimal

```python
# repro.py
from __future__ import annotations
from fastapi import APIRouter, Depends, status

def fake_dep(): pass
router = APIRouter()

@router.delete("/x", status_code=status.HTTP_204_NO_CONTENT)
async def del_x(_: None = Depends(fake_dep)) -> None: pass
# AssertionError: Status code 204 must not have a response body
```

```bash
py -c "import repro"
# Traceback (most recent call last):
#   ...
# AssertionError: Status code 204 must not have a response body
```

## Détection programmatique (avant commit)

Script de check rapide à exécuter ponctuellement :

```bash
# Lister les routers qui ont les 2 patterns
for f in app/routers/**/*.py; do
  if grep -l "from __future__ import annotations" "$f" > /dev/null && \
     grep -lE "status_code=(status\.)?HTTP_204_NO_CONTENT|status_code=204" "$f" > /dev/null; then
    echo "SUSPECT: $f"
  fi
done
```

Si le script remonte un fichier, vérifier manuellement que l'endpoint 204 n'a
pas `-> None`. Si oui → corriger.

## Anti-patterns à bloquer en review

1. ❌ Ajouter `from __future__ import annotations` en haut d'un router qui a
   déjà des endpoints 204 avec `-> None`
2. ❌ Ajouter un endpoint 204 `-> None` dans un router qui a déjà
   `from __future__ import annotations`
3. ❌ Pinner ruff/lint pour masquer la cascade qui cache ce bug. Si le lint
   échoue, **fix le lint** au lieu de skip les tests
4. ❌ Documenter le pattern bogué dans un docstring comme "feature" plutôt que
   le corriger

## Audit complet au 2026-05-20

Croisement des deux listes après PR #150 :

| Router | PEP 563 ? | 204 endpoint ? | Verdict |
|---|---|---|---|
| `teacher_attendance.py` | non (retiré #150) | oui | ✅ Safe |
| `reports.py` | oui | non | Safe |
| `student_documents.py` | oui | non | Safe |
| `grades.py` | oui | non | Safe |
| `council.py` | oui | non | Safe |
| `dren_stats.py` | oui | non | Safe |
| `auth.py`, `fees.py`, `timetable.py`, `enrollments.py`, `admin.py`, `super_admin/pats.py` | non | oui | Safe |

**Plus aucune intersection PEP 563 ∩ 204 dans le codebase.**

## Voir aussi

- Memory `project_session_2026_05_20_phase7b_ship_and_ci_cleanup.md` —
  incident fondateur + 3 bugs uncovered ensemble
- PR #150 — bump ruff 0.15.12 + fix migration 0030 chain + fix PEP 563/204
- Rule projet `preload-relations-after-commit.md` — autre classe de bugs
  latents masqués par CI cascade
- Rule projet `changelog.md` — un fix de cette classe va dans `### Fixed`
