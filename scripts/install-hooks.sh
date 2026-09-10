#!/bin/sh
# Branche les hooks versionnes de `.githooks/` sur ce clone.
#
# `core.hooksPath` fait lire les hooks dans le depot au lieu de `.git/hooks`,
# qui n'est pas versionne : les regles voyagent alors avec le code, et une
# correction profite a tout le monde au prochain pull.
#
#   sh scripts/install-hooks.sh
set -e

racine=$(git rev-parse --show-toplevel)
cd "$racine"
git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

printf '\nHooks branches sur .githooks/\n\n'
for h in .githooks/*; do
  [ -f "$h" ] || continue
  printf '  %-14s %s\n' "$(basename "$h")" "$(sed -n '2s/^# //p' "$h")"
done
printf '\nPour debrancher : git config --unset core.hooksPath\n\n'
