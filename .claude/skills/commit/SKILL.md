---
name: commit
description: Create a conventional commit for the backend. Use when the user asks to commit changes.
disable-model-invocation: true
---

Create a conventional commit for the KLASSCI backend following these steps:

1. Run `git status` to see all changed files
2. Run `git diff --staged` and `git diff` to review all changes
3. Run `git log --oneline -5` to check recent commit style

4. Analyze the changes and determine:
   - **type**: feat | fix | refactor | test | docs | chore | perf
   - **scope**: auth | enrollments | fees | timetable | grades | attendance | notifications | permissions | tenant | migrations
   - **description**: imperative English, ≤ 72 chars (e.g. "add enrollment status validation")

5. Stage only relevant files explicitly (NEVER `git add -A` or `git add .`)
   - Never stage: `.env`, `*.pyc`, `__pycache__/`, migration files unless intentional

6. Create the commit:
```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <description>

[optional body explaining WHY if not obvious]
EOF
)"
```

**Rules:**
- NO "Generated with Claude Code" or "Co-Authored-By" in commits
- NO WIP commits
- If multiple unrelated changes exist, ask the user to split into separate commits
- Always verify `git diff --staged` before committing

$ARGUMENTS
