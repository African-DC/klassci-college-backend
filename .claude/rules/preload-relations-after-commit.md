# Rule : selectinload toutes les relations consommées par le service après commit

## Quand s'active

Cette rule s'active automatiquement quand je modifie ou crée un fichier dans :
- `klassci-backend/app/repositories/*.py` (fonctions `get_X_by_id`, `list_X` qui retournent un model)
- `klassci-backend/app/services/*.py` (fonctions qui appellent `await db.commit()` puis lisent des attributs de relations)
- N'importe quel endpoint qui renvoie un `response_model` Pydantic dont la sérialisation parcourt des relations

## La règle

**Toute relation parcourue par le service après `await db.commit()` (ou par le PDF service, ou par Pydantic `model_validate` avec `from_attributes=True`) DOIT être incluse explicitement dans le `selectinload` du `get_X_by_id` du repo.**

Le `commit()` SQLAlchemy expire par défaut tous les attributs des objets — y compris les relations chargées. Si le code accède ensuite à `entity.relation.field`, SQLAlchemy déclenche un lazy-load qui requiert un greenlet contexte async actif. Si on n'en a pas (cas typique : pendant la sérialisation Pydantic ou un template Jinja), c'est le `MissingGreenlet` → exception non gérée → 500 plain text.

## Pourquoi cette rule existe

**4 occurrences du pattern le 2026-05-17** sur la même session :

1. `create_room` → `_room_to_response(room)` → Pydantic accède `room.created_at`/`updated_at` après commit → expired → lazy-load → MissingGreenlet
2. `create_payment` → `notif.dispatch` → `refreshed.enrollment_fee.enrollment.student.user_id` → chaîne pas selectinload → MissingGreenlet
3. `get_bulletin_pdf` → `pdf_service` → `bulletin.academic_year.name` → relation pas selectinload → MissingGreenlet
4. `get_teacher_full` → ancien Pydantic strip `classes` du response_model (différent pattern mais même classe de drift)

Symptôme commun : **500 Internal Server Error en plain text** (pas JSON détail) côté HTTP, ce qui rend le bug invisible côté FE (le client tombe en "Erreur serveur" générique).

## Pattern correct

### 1. Repository — selectinload exhaustif

Pour chaque relation que le service utilise dans le pipeline post-commit (sérialisation, notif, template PDF), l'inclure dans `selectinload` :

```python
async def get_payment_by_id(db: AsyncSession, payment_id: int) -> Payment | None:
    """Toutes les relations que create_payment / send_receipt consomment."""
    stmt = (
        select(Payment)
        .where(Payment.id == payment_id)
        .options(
            selectinload(Payment.enrollment_fee)
            .selectinload(EnrollmentFee.enrollment)
            .selectinload(Enrollment.student)
            .selectinload(Student.user),  # ← notif.dispatch_notification a besoin de student.user_id
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
```

### 2. Service — refetch via repo, ne JAMAIS commit puis `refresh(obj, ["selected_attrs"])`

```python
# ❌ FRAGILE — db.refresh narrow ne re-charge que les attributs nommés, et expire les autres
await db.commit()
await db.refresh(room, ["classes"])  # created_at/updated_at restent expired → lazy-load → BOOM
return _room_to_response(room)

# ✅ ROBUSTE — refetch propre via repo qui selectinload tout
await db.commit()
refreshed = await repo.get_room_by_id(db, room.id)
assert refreshed is not None
return _room_to_response(refreshed)
```

### 3. Pydantic `from_attributes=True` est piégé après commit

Quand `response_model.model_validate(orm_object)` parcourt les champs déclarés, chaque field qui correspond à une **relation expired** déclenche un lazy-load. Le service doit présenter un objet **complètement frais et chargé** à Pydantic.

## Checklist nouveau endpoint `create_X` / `update_X`

- [ ] Le service termine par `await db.commit()` + `refreshed = await repo.get_X_by_id(db, x.id)` (PAS `refresh(obj, [attrs])`)
- [ ] Le `repo.get_X_by_id` selectinload **toutes** les relations qu'on accède en aval (response_model nested, notif dispatch, PDF template, audit log)
- [ ] Si je vois un `MissingGreenlet` dans le BE log → tracer la chaîne d'accès et étendre le selectinload du repo

## Anti-patterns à bloquer en review

1. **`await db.refresh(obj, ["only_one_attr"])` après commit** → expire les autres attrs, lazy-load future inévitable
2. **`return _X_to_response(obj)` immédiatement après `await db.commit()` sans refetch** → audit Pydantic post-commit
3. **`selectinload(parent.relation)` mais le service accède `parent.relation.relation_of_relation`** → chaîne incomplète
4. **`assert refreshed is not None` absent** après refetch (None-handling implicite) → Python `AttributeError` cryptique au lieu d'un message clair
5. **Catch `MissingGreenlet` dans le service et fallback silencieux** → masque le bug, vrai fix ailleurs

## Pour les services existants — pattern de scan

Pour identifier les autres endpoints à risque, grep :

```bash
grep -rn "await db.commit()" app/services/ | head
grep -rn "await db.refresh" app/services/ | grep -v "test_"
```

Pour chaque match, lire le code qui suit (~10 lignes) et vérifier que toutes les `obj.relation.X` accédées sont selectinload dans le `get_X_by_id` du repo.

## Voir aussi

- Memory `project_session_2026_05_17_phase4_finances.md` — incident fondateur (paiement mobile_money)
- Memory `project_session_2026_05_17_phase3_academique.md` — incident `create_room`
- Memory `project_session_2026_05_17_phase5_attendance_bulletins.md` — incident `get_bulletin_pdf`
- Rule globale `~/.claude/rules/iroko-versioning.md` (pas direct lié)
- Rule projet `singleton-lazy-bootstrap.md` (pattern lazy-create voisin)
- SQLAlchemy docs : [`expire_on_commit`](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#session-expire-on-commit) — on pourrait passer `expire_on_commit=False` au sessionmaker pour réduire le risque, mais introduit d'autres pièges (stale data après commit, surtout en concurrent writes). Préférer la discipline selectinload.
