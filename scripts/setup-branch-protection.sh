#!/usr/bin/env bash
# KLASSCI College — Setup branch protection develop + staging + main via gh API
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

# La CI de chaque depot : elle tourne sur toute PR vers develop, staging et
# main, sans filtre de chemins, et elle est verte sur develop.
BE_CI='"Lint & Type Check", "Tests", "Alembic migrations idempotence"'
FE_CI='"Lint & Type Check", "Build Check", "Unit Tests"'

# Les trois controles d'hygiene (hygiene-commits.yml). Ils ne lisent que des
# messages de commit, le titre et le corps de la PR : quelques secondes, aucune
# installation. Requis, parce qu'un garde-fou consultatif se contourne en ne le
# regardant pas, et que c'est exactement ce qui a laisse deux signatures d'outil
# entrer dans l'historique du backend.
HYGIENE='"Messages de commit", "Corps de la pull request", "Revue de qualite declaree"'

# Un controle requis dont le workflow n'existe pas encore sur la branche ne se
# declenche jamais : chaque PR attend alors « Expected » pour toujours. Au
# 2026-09-23, 24 PR etaient ouvertes sur les deux depots, presque toutes de
# Dependabot, sur des branches qui ne contiennent pas hygiene-commits.yml.
#
# Le script n'exige donc l'hygiene que la ou son workflow est deja present, et
# le dit. Une fois le workflow fusionne, une relance ajoute les trois
# controles. Elle ne peut pas les retirer par erreur : une panne de `gh`
# arrete le script avant toute ecriture, au lieu d'etre lue comme « absent ».
#
# « Absent » se conclut sur un 404, et seulement apres avoir verifie que la
# branche existe : GitHub rend aussi un 404 pour un depot ou une branche
# introuvable. Toute autre erreur (reseau, jeton expire) arrete le script. La
# lire comme « absent » retirerait l'hygiene en silence, en affichant un
# message faux.
checks_for() {
  local repo="$1" branch="$2" ci="$3" erreur
  if ! gh api "repos/$repo/branches/$branch" --jq .name >/dev/null 2>&1; then
    echo "✗ $repo @ $branch introuvable ou inaccessible : arret, rien n'a ete ecrit pour elle." >&2
    return 1
  fi
  if erreur=$(gh api "repos/$repo/contents/.github/workflows/hygiene-commits.yml?ref=$branch" 2>&1 >/dev/null); then
    echo "  · $branch : CI + hygiene des commits" >&2
    printf '{"strict": true, "contexts": [%s, %s]}' "$ci" "$HYGIENE"
  elif printf '%s' "$erreur" | grep -q 'HTTP 404'; then
    echo "  · $branch : CI seule (hygiene-commits.yml pas encore sur cette branche)" >&2
    printf '{"strict": true, "contexts": [%s]}' "$ci"
  else
    echo "✗ impossible de savoir si hygiene-commits.yml existe sur $repo @ $branch :" >&2
    echo "  $erreur" >&2
    return 1
  fi
}

# `develop` est la branche ou le controle d'hygiene compte vraiment : c'est la
# que le titre d'une PR devient le sujet d'un commit, et qu'un mauvais titre se
# corrige encore d'un clic. Sur `main` et `staging`, les PR sont des mises en
# production dont les commits sont deja partages : le controle les laisse
# passer. Sans `develop` ici, la regle serait consultative a l'endroit meme ou
# elle peut encore agir.
#
# `PUT` remplace la protection existante en entier. Au 2026-09-22, aucune des
# trois branches n'etait protegee sur les deux depots (l'API renvoyait 404) :
# lancer ce script n'ecrasait donc aucun reglage fait a la main.
#
# Toutes les lectures precedent la premiere ecriture : aucune branche n'est
# reecrite tant qu'une lecture a echoue. Ce n'est pas un « tout ou rien » :
# si un `PUT` echouait lui-meme (erreur 5xx), les branches deja ecrites le
# resteraient. Chacune serait correcte, aucun controle ne serait retire, et
# une relance terminerait le travail.
#
# Chaque resultat passe par une affectation simple : sous `set -e`, un echec
# dans `$(...)` place directement en argument n'arrete pas le script (et
# `local x=$(...)` non plus), si bien que `protect_branch` recevait un JSON
# vide. Une affectation simple, elle, propage l'echec.
declare -a plan_repo=() plan_branch=() plan_checks=()
for branch in develop staging main; do
  for i in 0 1; do
    if [ "$i" -eq 0 ]; then ci="$BE_CI"; else ci="$FE_CI"; fi
    checks=$(checks_for "${REPOS[$i]}" "$branch" "$ci")
    plan_repo+=("${REPOS[$i]}")
    plan_branch+=("$branch")
    plan_checks+=("$checks")
  done
done

for k in "${!plan_repo[@]}"; do
  protect_branch "${plan_repo[$k]}" "${plan_branch[$k]}" "${plan_checks[$k]}"
done

echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "✓ Branch protection configurée :"
echo "  - develop, staging et main sur les 2 repos"
echo "  - CI required (lint + tests + migrations BE / lint + build + tests FE)"
echo "  - Hygiene des commits required la ou hygiene-commits.yml existe deja (voir ci-dessus)"
echo "  - Pas de required reviews (solo dev)"
echo "  - enforce_admins=false (owner peut bypass en cas d'urgence)"
echo "  - required_conversation_resolution=true (close threads avant merge)"
echo "═══════════════════════════════════════════════════════════════════════"
