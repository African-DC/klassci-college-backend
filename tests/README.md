# tests/ — Tests Pytest

Tests automatises du backend KLASSCI.

## Structure

```
tests/
├── conftest.py    Fixtures partagees (client, DB, factories, utilisateurs)
├── routers/       Tests HTTP des endpoints (un fichier par router)
└── services/      Tests unitaires des services
```

## Lancer les tests

```bash
pytest tests/ -v                              # Tous les tests
pytest tests/ -v --cov=app --cov-report=html  # Avec coverage HTML
pytest tests/routers/test_enrollments.py -v   # Un fichier specifique
/run-tests                                     # Via Claude skill (lint + types + tests)
```

## Conventions

- Un fichier par router : `test_enrollments.py`, `test_fees.py`, `test_grades.py`...
- Tester : happy path + erreurs principales (404, 403, 422, 400)
- Utiliser des factories, pas de fixtures statiques
- Couverture minimale : **70%** (bloquant en CI)

## Fixtures a creer dans conftest.py

| Fixture | Usage |
|---------|-------|
| `async_client` | Client HTTP de test |
| `db_session` | Session DB isolee sur base de test |
| `test_tenant` | Tenant de test |
| `admin_token` | JWT admin pour les requetes protegees |
| `teacher_token` | JWT enseignant |
| `student_token` | JWT etudiant |
| `academic_year` | Annee academique active de test |
| `test_class` | Classe de test rattachee a une annee |
