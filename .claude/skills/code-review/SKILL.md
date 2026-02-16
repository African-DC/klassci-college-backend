---
name: code-review
description: Review backend Python/FastAPI code for bugs, security issues, performance, and adherence to KLASSCI conventions. Use when asked to review code or before creating a PR.
disable-model-invocation: true
allowed-tools: Bash(git *), Read, Grep, Glob
---

Perform a thorough code review of the KLASSCI backend changes.

## Step 1 — Get the changes
```bash
git diff develop...HEAD
git diff --stat develop...HEAD
```

## Step 2 — Review checklist

### Security (CRITICAL — block PR if any found)
- [ ] No hardcoded permissions (no `if user.role == "admin"`)
- [ ] No SQL string interpolation
- [ ] No secrets in code
- [ ] JWT tenant_id validated on every protected route
- [ ] Audit log present on all sensitive mutations (payments, grades, enrollments)
- [ ] Input validated via Pydantic before any DB operation

### Async / SQLAlchemy
- [ ] All DB functions are `async def`
- [ ] SQLAlchemy 2.0 style (`select()` not `db.query()`)
- [ ] Transactions used for multi-write operations
- [ ] No N+1 queries (use `selectinload` or `joinedload`)

### Architecture
- [ ] Business logic in services, not routers
- [ ] Routers only handle HTTP concerns (validation, response format)
- [ ] Repository pattern for DB access
- [ ] No cross-tenant data access

### Code Quality
- [ ] Functions < 50 lines
- [ ] No duplicated logic (DRY)
- [ ] Meaningful variable names
- [ ] No commented-out code
- [ ] Proper error handling (not bare `except:`)

### Tests
- [ ] New features have tests
- [ ] Bug fixes have regression tests
- [ ] Happy path + error cases covered

## Step 3 — Report

Format your review as:

**🔴 BLOCKING** — Must fix before merge:
- [issue] in `file:line`

**🟡 IMPORTANT** — Should fix:
- [issue] in `file:line`

**🟢 SUGGESTIONS** — Nice to have:
- [suggestion]

**✅ GOOD** — What was done well

$ARGUMENTS
