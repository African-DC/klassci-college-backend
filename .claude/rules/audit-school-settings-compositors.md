# Rule : Audit school_settings compositors à chaque ajout de field

## Quand s'active

Cette rule s'active automatiquement quand :
- Tu ajoutes une colonne au model `SchoolSettings` (`app/models/academic.py`)
- Tu crées une migration alembic qui touche la table `school_settings`
- Tu ajoutes un field au schema `SchoolInfoUpdate` ou `SchoolSettingsResponse`
- Tu modifies un PDF generator pour consommer un nouveau field du `school_settings` dict

## Règle absolue

**Pour CHAQUE nouveau field ajouté à `SchoolSettings`, tu DOIS auditer manuellement les 9 service compositors PDF et ajouter ce field au dict construit par leur helper `_get_school_settings*()`.**

Pas d'exception. Le compilateur n'attrape pas le drift — un compositor oublié continue de fonctionner sans crash, mais le PDF qui en dépend ignore silencieusement le nouveau field et retombe sur le fallback hardcoded. **Bug latent invisible** sans inspection visuelle PDF par PDF.

## Pourquoi cette rule existe

**Incident fondateur 2026-05-18** : la session précédente a livré la migration 0029 (`primary_color`, `accent_color`, `motto`, `website` sur `school_settings`) et a refait les 10 generators PDF pour consommer ces fields via `PDFTheme.from_school(dict)`. La session a prétendu avoir testé 9/9 PDFs E2E avec theme custom (purple/green).

**En réalité, 6 services sur 9 ignoraient silencieusement le theme école** :
- `class_roster_service.py` — liste de classe
- `council_service.py` — PV conseil de classe
- `enrollment_form_service.py` — fiche d'inscription
- `reports_service.py` — bulletin trimestre
- `student_documents_service.py` — certificat scolarité + attestation fréquentation
- `timetable_service.py` — emploi du temps

Tous retombaient sur le fallback KLASSCI bleu/orange car leur helper `_get_school_settings_dict()` était un dictionary builder manuel qui ne reprenait pas les 4 nouveaux fields. Aucun crash → bug invisible. Marcel ne s'en serait probablement jamais aperçu sans audit explicite à la session suivante.

Coût : ~30 minutes de debug + 6 services à patcher + 1 selectinload manquant trouvé en bonus (5e MissingGreenlet).

## Pattern correct — checklist obligatoire

Quand tu ajoutes un field à `SchoolSettings` :

### Étape 1 — Trouver les compositors

```bash
grep -rn "school_name.*settings\.school_name" klassci-backend/app/services/
```

Tu dois trouver 9 fichiers (au 2026-05-18) :
- `daily_cash_book_service.py:32`
- `class_roster_service.py:28`
- `council_service.py:199`
- `fee_statement_service.py:35`
- `reports_service.py:367`
- `student_documents_service.py:42`
- `enrollment_form_service.py:35`
- `timetable_service.py:605` (inline, pas dans un helper)
- `payments/receipt.py:29`

⚠️ `matricule_service.py` apparaît aussi dans le grep mais ce n'est PAS un compositor PDF (il utilise `school_settings.school_name` pour générer le matricule — pas pour passer un dict à un generator). À ignorer.

### Étape 2 — Lire le helper pattern de référence

Pattern canonique (par exemple `daily_cash_book_service.py:24-45`) :

```python
async def _get_school_settings(db: AsyncSession) -> dict:
    stmt = select(SchoolSettings).limit(1)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings is None:
        return {"school_name": "Etablissement"}
    return {
        "school_name": settings.school_name,
        "ministry_code": settings.ministry_code,
        "address": settings.address,
        "phone": settings.phone,
        "email": settings.email,
        "logo_url": settings.logo_url,
        "signature_image_url": settings.signature_image_url,
        "head_master_name": settings.head_master_name,
        "head_master_title": settings.head_master_title,
        "primary_color": settings.primary_color,
        "accent_color": settings.accent_color,
        "website": settings.website,
        "motto": settings.motto,
        # ← AJOUTE TON NOUVEAU FIELD ICI
    }
```

### Étape 3 — Ajouter le field dans CHAQUE compositor

Pour les 8 helpers `_get_school_settings*()` et l'inline timetable_service.py:605, ajouter la même ligne :

```python
        "ton_nouveau_field": settings.ton_nouveau_field,
```

Et pour timetable_service.py (inline, ternaire) :

```python
        "ton_nouveau_field": settings.ton_nouveau_field if settings else None,
```

### Étape 4 — Vérifier que le generator consomme

Si ton field est utilisé dans le PDF, vérifier que le generator (`app/services/pdf/<name>.py`) le lit du dict ou via `PDFTheme.from_school(dict)`. Si c'est un theme field, étendre la dataclass `PDFTheme` dans `theme.py`.

### Étape 5 — Test E2E par PDF

Reset DB avec une valeur custom non-default :

```sql
UPDATE school_settings SET ton_nouveau_field = 'valeur_test';
```

Régénérer les 10 PDFs et vérifier visuellement que la valeur custom apparaît. Si le PDF ignore la valeur custom, tu as oublié un compositor.

## Anti-patterns à bloquer en review

1. **Ajouter une migration `school_settings` sans toucher les 9 compositors** → bug latent garanti
2. **Tester seulement 1 PDF après avoir ajouté un field** → 6 sur 9 silencieux, faux positif
3. **Helpers `_get_school_settings*()` divergents** (l'un a 13 fields, l'autre 5) → fragmente la vérité de l'identité école
4. **Inline dict construction comme dans `timetable_service.py:604-613`** → encore plus facile à oublier, à refactorer en helper partagé un jour

## Solution long terme (dette tech)

Le pattern actuel `_get_school_settings_dict()` répliqué 9 fois est intrinsèquement fragile. Refactor proposé :

**Option A** : Mixin Pydantic
```python
class SchoolSettingsResponse(BaseModel):
    # ... tous les fields ...

    def to_pdf_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
```

**Option B** : Helper unique `app/services/_school_settings_helper.py`
```python
async def load_school_settings_for_pdf(db: AsyncSession) -> dict[str, Any]:
    """1 point de vérité pour TOUS les compositors PDF."""
    settings = (await db.execute(select(SchoolSettings).limit(1))).scalar_one_or_none()
    if settings is None:
        return {"school_name": "Etablissement"}
    return {col.name: getattr(settings, col.name) for col in SchoolSettings.__table__.columns}
```

Puis les 9 compositors importent juste `from app.services._school_settings_helper import load_school_settings_for_pdf`.

Pas fait au 2026-05-18 (scope minimal demandé) mais à prévoir dès qu'on touche encore au model.

## Voir aussi

- Memory `project_session_2026_05_18_pdf_audit_compositors.md` — incident fondateur + fix
- Memory `project_session_2026_05_18_pdf_premium_complete.md` — session qui a créé le bug
- Rule projet `preload-relations-after-commit.md` — bug latent voisin (relations non selectinload)
- Rule globale `~/.claude/rules/no-mvp-only-premium.md` — production-grade dès v1 inclut visual check par PDF
