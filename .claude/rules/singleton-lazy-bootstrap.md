# Rule : Singleton lazy bootstrap pour entités fondation

## Quand s'active

Quand tu écris ou modifies un endpoint BE qui retourne un **singleton par tenant** : `school_settings`, `current_academic_year` (si concept "unique"), `default_grading_scale`, etc.

## Règle

**Le GET d'un singleton ne doit JAMAIS renvoyer 404 quand la table est vide pour un tenant légitime.** Le service doit upsert paresseusement avec un placeholder éditable, puis return la row.

## Pourquoi

En prod KLASSCI College, un nouveau tenant est créé par la signup wizard. À ce moment :
- L'admin n'a pas encore rempli les paramètres de l'école
- Le wizard ne pré-remplit pas tous les champs (juste school_name minimum via `provision_tenant`)
- L'admin va sur `/admin/settings` immédiatement après son 1er login

Si le BE retourne 404 → le FE affiche "Connexion impossible" → l'admin croit que tout est cassé. C'est l'**onboarding qui se passe le plus mal** : 0 valeur générée avant le 1er incident.

**Voir** [feedback memory `feedback_no_seed_in_prod_handle_empty`](../../../../.claude/projects/C--Users-yabla-Downloads-dev-KLASSCI-college/memory/feedback_no_seed_in_prod_handle_empty.md)

## Pattern correct

```python
async def get_school_settings(db: AsyncSession) -> SchoolSettings:
    """Get the school settings singleton.

    Lazily provisions a placeholder row on the first call so a fresh tenant
    can land on /admin/settings without a 404 — the admin then fills the
    real name/address/etc via the UI form.
    """
    stmt = select(SchoolSettings).limit(1)
    school = (await db.execute(stmt)).scalar_one_or_none()
    if school is None:
        school = SchoolSettings(school_name="Mon établissement")
        db.add(school)
        await db.flush()
        await db.commit()  # critique : le service GET ne commit pas par défaut
    return school
```

## Points clés

1. **Placeholder neutre et éditable** : `"Mon établissement"`, jamais une chaîne vide (qui pourrait casser des templates downstream)
2. **`await db.commit()` explicite** : `get_db()` ne commit pas automatiquement, sans commit la row est rollback
3. **Toujours dans le service**, pas dans le router : le router reste mince
4. **Idempotent** : si plusieurs requêtes concurrent arrivent sur un fresh tenant, la 1re crée, les autres trouvent et retournent

## Anti-patterns à bloquer en review

```python
# ❌ Force 404 quand le tenant est légitime mais juste vide
if school is None:
    raise NotFoundError("SchoolSettings", 0)
```

```python
# ❌ Auto-create sans commit → la row n'est jamais persistée
if school is None:
    school = SchoolSettings(school_name="Mon établissement")
    db.add(school)
    # manque await db.flush() + await db.commit()
return school
```

```python
# ❌ Placeholder string vide
school = SchoolSettings(school_name="")  # casse les bulletins PDF, le header, etc.
```

## Quand NE PAS appliquer

- **Entités à création explicite** : un étudiant n'a pas de "singleton vide auto-créé". Le 404 sur GET /admin/students/999 est légitime.
- **Tables à plusieurs rows** : academic_years, classes, teachers... Le 404 sur GET d'un id inconnu est normal.
- **Singletons stricts where empty = intentional** : si l'absence de la row PORTE une sémantique métier (ex: "pas encore de bulletin publié"), gérer côté FE (empty state) plutôt qu'auto-create.

## Voir aussi

- Rule globale `~/.claude/rules/no-mvp-only-premium.md` — production-grade dès v1 = un onboarding propre
- Memory `feedback_no_seed_in_prod_handle_empty.md`
- Rule FE `klassci-frontend/.claude/rules/empty-state-by-role.md`
