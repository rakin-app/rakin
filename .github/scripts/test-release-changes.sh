#!/usr/bin/env bash
# Tests for release-changes.sh, against a throwaway repository:
#   v1  (lightweight)  a file
#   v2  (annotated)    a migration
#   v3  (annotated)    a plain change
# The checks are functions that `check` calls by name:
# shellcheck disable=SC2329,SC2016  # SC2016: backticks are Markdown here
set -euo pipefail

script=$(cd "$(dirname "$0")" && pwd)/release-changes.sh
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
cd "$dir"
git init -q
git config user.email t@example.com
git config user.name t
git config tag.gpgSign false
commit() { mkdir -p "$(dirname "$1")"; echo "$2" >"$1"; git add "$1"; git commit -qm "$2"; }
commit README "first"
git tag v1
commit backend/alembic/versions/0002_x.py "add a table (#2)"
git tag -a v2 -m "v2: the table" -m "Migration 0002."
commit README "a plain change (#3)"
git tag -a v3 -m "v3: plain"

fails=0
check() { # check <description> <command...>
  local what=$1; shift
  if "$@"; then echo "ok   - $what"; else echo "FAIL - $what"; fails=1; fi
}
run() { "$script" "$@" >"$dir/out" 2>&1; }
said() { grep -qF -- "$1" "$dir/out"; }
not_said() { ! said "$1"; }

check "refuses no tag" bash -c "! '$script' >/dev/null 2>&1"
check "refuses a tag that does not exist" bash -c "! '$script' v9 >/dev/null 2>&1"

run v2 v1
check "names the tag" said '# Release v2 to production'
check "names what production runs" said '| Production runs now | `v1` |'
check "prints the tag's notes" said "Migration 0002."
check "lists the commits since production's tag" said "add a table (#2)"
check "lists the migrations" said '- `backend/alembic/versions/0002_x.py`'
check "flags them" said "Has migrations: rollback is restart-only."

run v3 v2
check "a release without migrations says None" said "None."
check "and is not flagged" not_said "Has migrations"
check "only commits since production's tag" not_said "add a table"

run v3 v1
check "a release over two tags sees the migration between" said "Has migrations"

run v1
check "a lightweight tag has no notes" said "lightweight tag"
check "no production tag: the changes cannot be listed" said "cannot be listed"
check "and it is treated as having migrations" said "with migrations"

run v3 v0
check "an unknown production tag is named" said '`v0` (not a tag in this repository)'

run v3 v3
check "production already on the commit: no changes" said "None: production already runs this commit."

run --rollback v1 v3
check "a rollback says so" said "# Roll production back to v1"
check "lists the commits leaving production" said "Commits leaving production (v1..v3)"
check "and the migrations that stay applied" said "These migrations stay applied"

exit "$fails"
