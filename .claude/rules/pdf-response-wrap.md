# Rule : tout endpoint PDF doit passer par `pdf_response`

## Quand s'active

Cette rule s'active automatiquement quand :
- Tu crées un nouvel endpoint qui renvoie `media_type="application/pdf"`
- Tu modifies un endpoint existant qui retourne un `Response(content=pdf_bytes, ...)`
- Tu ajoutes un service `generate_*_pdf()` qui appelle WeasyPrint

## La règle

**Tout endpoint qui renvoie un PDF doit utiliser le helper
`app.routers._pdf_helpers.pdf_response`**. Pas de `Response(content=...,
media_type="application/pdf", ...)` direct dans un router.

```python
from app.routers._pdf_helpers import pdf_response

@router.get("/{resource_id}/pdf")
async def get_resource_pdf(
    resource_id: int,
    _: None = require_permission("..."),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    return await pdf_response(
        lambda: service.get_pdf(db, resource_id),
        filename=f"resource-{resource_id}.pdf",
        error_context=f"resource {resource_id}",
    )
```

Pour les services PDF synchrones (sans `await`), encapsuler dans une closure async :

```python
data = await service.fetch_data(db, ...)
settings = await load_school_settings_for_pdf(db)

async def _generate() -> bytes:
    return generate_resource_pdf(data, settings)

return await pdf_response(
    _generate,
    filename=...,
    error_context=...,
)
```

Param `disposition="attachment"` pour forcer le download au lieu d'un preview
navigateur (utile pour les exports Excel-like : EDT, bordereau journalier).

## Pourquoi cette rule existe

**Incident fondateur 2026-05-20** (visual-check E2E /admin/reports) : le
téléchargement d'un bulletin PDF en local Windows déclenchait un
`OSError: cannot load library 'gobject-2.0-0'` côté WeasyPrint (GTK runtime
absent). L'exception non gérée remontait jusqu'à Starlette qui renvoyait
un **`500 Internal Server Error` plain-text** (21 bytes).

Conséquences cascadées :
1. Le `text/plain` BYPASS le `CORSMiddleware` Starlette → aucun header
   `Access-Control-Allow-Origin` ajouté
2. Le browser bloque la réponse côté FE (CORS policy)
3. L'admin clique « Télécharger », ne voit rien — **silent failure UX**
4. Le FE tombait dans un `catch` générique « Erreur 500 » sans info exploitable

Le pattern correct : lever une `HTTPException` dans le router → FastAPI/Starlette
applique le pipeline normal → CORS s'applique → réponse JSON
`{detail: "..."}` exploitable par le FE pour un toast utilisateur.

## Pattern correct (helper canonique)

`app/routers/_pdf_helpers.py::pdf_response(factory, *, filename, error_context, disposition="inline")` :

- `factory` : coroutine sans args produisant `bytes`
- Catch `OSError` → message explicite GTK/Cairo missing
- Catch `Exception` → message générique avec contexte
- `disposition="inline"` (preview) ou `"attachment"` (download forcé)
- Réponse 500 = JSON `{detail}` avec headers CORS appliqués

## Couverture actuelle (2026-05-20)

10 endpoints PDF — 100% via `pdf_response` :

| Router | Endpoint | Disposition |
|---|---|---|
| `reports.py` | `/bulletins/{id}/pdf` | inline |
| `council.py` | `/{class_id}/{trimester}/pdf` | inline |
| `class_documents.py` | `/{class_id}/roster` | inline |
| `enrollment_payments.py` | `/{id}/statement` | inline |
| `enrollment_payments.py` | `/{id}/form` | inline |
| `payments.py` | `/daily-cash-book` | inline |
| `payments.py` | `/{id}/receipt` | inline |
| `student_documents.py` | `/{id}/documents/certificat-scolarite.pdf` | inline |
| `student_documents.py` | `/{id}/documents/attestation-frequentation.pdf` | inline |
| `timetable.py` | `/export-pdf` | attachment |

## Anti-patterns à bloquer en review

1. ❌ `Response(content=pdf_bytes, media_type="application/pdf", headers=...)`
   dans un router → wrap obligatoire dans `pdf_response`
2. ❌ `try/except` ad-hoc dans le router qui re-raise un `HTTPException`
   custom → utiliser le helper centralisé
3. ❌ Service `get_*_pdf` qui catch `OSError` lui-même et retourne `None` ou
   bytes vides → la responsabilité du wrap est dans le router, pas le service
4. ❌ Endpoint qui appelle WeasyPrint sans wrap → silent failure garanti
5. ❌ Helper local `_make_pdf_response()` dans un router → utiliser le
   `_pdf_helpers.py` partagé

## Voir aussi

- Memory `project_session_2026_05_20_visual_check_e2e.md` — incident fondateur
- `app/routers/_pdf_helpers.py` — implémentation canonique
- FE `lib/api/client.ts::apiFetchBlob` — propage le `{detail}` BE comme
  `error.message` côté FE pour permettre un toast utilisateur exploitable
- Rule projet `audit-school-settings-compositors.md` — autre rule sur la
  cohérence cross-PDF des compositors
