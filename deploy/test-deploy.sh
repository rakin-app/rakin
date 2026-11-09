#!/usr/bin/env bash
# Tests for deploy.sh, with a fake `docker` that records its calls.
# The checks are functions that `check` calls by name:
# shellcheck disable=SC2329
set -euo pipefail

src=$(cd "$(dirname "$0")" && pwd)
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
cp "$src/deploy.sh" "$dir/"
cat >"$dir/docker" <<'SH'
#!/usr/bin/env bash
echo "RAKIN_TAG=$RAKIN_TAG $*" >>"$(dirname "$0")/calls"
if [ -n "${FAIL_ON:-}" ] && [[ "$*" == *"$FAIL_ON"* ]]; then exit 1; fi
SH
chmod +x "$dir/docker"
export DOCKER=$dir/docker

fails=0
check() { # check <description> <command...>
  local what=$1; shift
  if "$@"; then echo "ok   - $what"; else echo "FAIL - $what"; fails=1; fi
}
run() { : >"$dir/calls"; "$dir/deploy.sh" "$@" >"$dir/out" 2>&1; }
refused() { ! "$dir/deploy.sh" "$@" >/dev/null 2>&1; }
called() { grep -q -- "$1" "$dir/calls"; }
not_called() { ! called "$1"; }
line_of() { grep -n -- "$1" "$dir/calls" | head -n 1 | cut -d: -f1; }
migrates_first() { [ "$(line_of 'run --rm migrate')" -lt "$(line_of ' up -d')" ]; }
tag_in_env() { [ "$(grep -c '^RAKIN_TAG=' "$dir/.env")" = 1 ] && grep -qx "RAKIN_TAG=$1" "$dir/.env"; }
env_mode_is() { [ "$(stat -c %a "$dir/.env" 2>/dev/null || stat -f %Lp "$dir/.env")" = "$1" ]; }
last_release_is() { [ "$(tail -n 1 "$dir/releases.log" | cut -f2-)" = "$1" ]; }
said() { grep -q -- "$1" "$dir/out"; }
not_said() { ! said "$1"; }

check "refuses to run without .env" refused v1

printf 'SECRET_KEY=s\nRAKIN_TAG=v1\nPOSTGRES_PASSWORD=p\n' >"$dir/.env"
chmod 600 "$dir/.env"

check "refuses a tag that is not an image tag" refused "v2;rm -rf /"
check "refuses no tag" refused

run v2
check "a deploy pulls the new tag" called "RAKIN_TAG=v2 compose --profile migrate pull"
check "a deploy migrates" called "RAKIN_TAG=v2 compose --profile migrate run --rm migrate"
check "migrations run before anything restarts" migrates_first
check "a deploy restarts on the new tag" called "RAKIN_TAG=v2 compose up -d --wait"
check "a deploy records the tag in .env, once" tag_in_env v2
check "the rest of .env is kept" grep -qx "SECRET_KEY=s" "$dir/.env"
check ".env keeps its mode" env_mode_is 600
check "a deploy is logged with the previous tag" last_release_is "$(printf 'deploy\tv2\tv1')"

run --rollback v1
check "a rollback never migrates" not_called "run --rm migrate"
check "a rollback restarts on the old tag" called "RAKIN_TAG=v1 compose up -d --wait"
check "a rollback records the tag" tag_in_env v1
check "a rollback is logged" last_release_is "$(printf 'rollback\tv1\tv2')"

FAIL_ON="run --rm migrate" run v3 || true
check "a failed migration does not restart anything" not_called " up -d"
check "a failed deploy leaves .env on the live tag" tag_in_env v1
check "a failed migration says the old release still runs" said "v1 still runs"

FAIL_ON=" up -d" run v3 || true
check "a failed restart leaves .env on the live tag" tag_in_env v1
check "a failed restart names the rollback" said "--rollback v1"

printf 'SECRET_KEY=s\nRAKIN_TAG=<v0.1.0>\n' >"$dir/.env"
FAIL_ON=" up -d" run v1 || true
check "a first deploy's failure names no rollback" not_said "--rollback"
check "a first deploy's failure names no placeholder" not_said "<v0.1.0>"
run v1
check "a first deploy replaces the placeholder" tag_in_env v1
check "a first deploy is logged with no previous tag" last_release_is "$(printf 'deploy\tv1\t-')"

FAIL_ON="image prune" check "a failed image prune does not fail the deploy" run v2
check "a failed image prune still records the release" tag_in_env v2

exit "$fails"
