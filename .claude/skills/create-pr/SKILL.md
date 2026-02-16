---
name: create-pr
description: Create a pull request for the backend. Use when the user asks to create a PR or push their branch.
disable-model-invocation: true
allowed-tools: Bash(git *), Bash(gh *)
---

Create a pull request for the KLASSCI backend following the team workflow.

## Step 1 — Verify state
```bash
git status
git log develop..HEAD --oneline
git diff develop...HEAD --stat
```

## Step 2 — Push branch
```bash
git push -u origin HEAD
```

## Step 3 — Run code review mentally
Before creating the PR, verify:
- No `.env` or secrets staged
- All commits follow conventional format
- CI will pass (ruff + mypy + pytest)

## Step 4 — Create the PR targeting `develop`

```bash
gh pr create \
  --base develop \
  --title "<type>(<scope>): <description>" \
  --body "$(cat <<'EOF'
## Summary
- [What this PR does in 1-3 bullet points]

## Changes
- `file.py` — [what changed and why]

## Type of change
- [ ] feat — new feature
- [ ] fix — bug fix
- [ ] refactor — no behavior change
- [ ] test — tests only
- [ ] chore — maintenance

## Testing
- [ ] Unit tests added/updated
- [ ] Tested locally with `pytest tests/ -v`
- [ ] No regressions

## API changes
- [ ] No API changes
- [ ] New endpoints documented in OpenAPI
- [ ] Breaking change (requires version bump)

## DB changes
- [ ] No DB changes
- [ ] Migration added and tested
- [ ] Migration is reversible (downgrade tested)

## Checklist
- [ ] Ruff passes: `ruff check app/`
- [ ] Mypy passes: `mypy app/`
- [ ] Tests pass: `pytest tests/ -v`
- [ ] No hardcoded permissions
- [ ] Audit logs on sensitive mutations
EOF
)"
```

## Step 5 — Output
Return the PR URL to the user.

$ARGUMENTS
