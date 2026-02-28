---
name: run-tests
description: Run backend tests with coverage report. Use before creating a PR or when asked to run tests.
disable-model-invocation: true
---

Run the full KLASSCI backend quality checks:

## 1. Lint check
```bash
ruff check app/ tests/
```
Fix any errors before continuing.

## 2. Format check
```bash
ruff format --check app/ tests/
```

## 3. Type check
```bash
mypy app/ --ignore-missing-imports
```

## 4. Run tests with coverage
```bash
python -m pytest tests/ -v --cov=app --cov-report=term-missing --cov-fail-under=70
```

## 5. Report results
Summarize:
- ✅/❌ Lint
- ✅/❌ Types
- ✅/❌ Tests (X passed, Y failed)
- 📊 Coverage: X%
- Any failing tests with their error messages

If tests fail, analyze the errors and suggest fixes — do NOT auto-fix without asking first.

$ARGUMENTS
