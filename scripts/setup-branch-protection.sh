#!/usr/bin/env bash
# KLASSCI College — Setup branch protection main + staging via gh API
#
# À exécuter une seule fois après les premières merges P0a vers develop puis
# vers main (en P0a final). Solo dev : pas de required reviews.

set -euo pipefail

REPOS=(
  "African-DC/klassci-college-backend"
  "African-DC/klassci-college-frontend"
)

protect_branch() {
  local repo="$1"
  local branch="$2"
  local checks_json="$3"

  echo "▶ Protecting $repo @ $branch..."

  gh api -X PUT "repos/$repo/branches/$branch/protection" \
    --input - <<EOF
{
  "required_status_checks": $checks_json,
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
EOF
  echo "  ✓ $branch protected on $repo"
}

# Backend — required CI checks : "Lint & Type Check", "Tests", "Alembic migrations idempotence"
BE_CHECKS='{"strict": true, "contexts": ["Lint & Type Check", "Tests", "Alembic migrations idempotence"]}'

# Frontend — required CI checks : "Lint & Type Check", "Build Check", "Unit Tests"
FE_CHECKS='{"strict": true, "contexts": ["Lint & Type Check", "Build Check", "Unit Tests"]}'

protect_branch "${REPOS[0]}" "main"    "$BE_CHECKS"
protect_branch "${REPOS[0]}" "staging" "$BE_CHECKS"
protect_branch "${REPOS[1]}" "main"    "$FE_CHECKS"
protect_branch "${REPOS[1]}" "staging" "$FE_CHECKS"

echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "✓ Branch protection configurée :"
echo "  - main et staging sur les 2 repos"
echo "  - CI required (lint + tests + migrations BE / lint + build + tests FE)"
echo "  - Pas de required reviews (solo dev)"
echo "  - enforce_admins=false (owner peut bypass en cas d'urgence)"
echo "  - required_conversation_resolution=true (close threads avant merge)"
echo "═══════════════════════════════════════════════════════════════════════"
