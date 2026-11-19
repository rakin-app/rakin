#!/usr/bin/env bash
# Tests for verify.sh, with a fake `docker` whose answers come from the
# environment: PS (what `compose ps` lists), CURRENT and HEADS (Alembic's
# stdout), LOGS (the api's and jobs' log lines).
# The checks are functions that `check` calls by name:
# shellcheck disable=SC2329
set -euo pipefail

src=$(cd "$(dirname "$0")" && pwd)
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
cp "$src/verify.sh" "$dir/"
cat >"$dir/docker" <<'SH'
#!/usr/bin/env bash
echo "$*" >>"$(dirname "$0")/calls"
case "$*" in
  "compose ps "*) printf '%b' "$PS" ;;
  *"alembic current") echo "INFO  [alembic.runtime.migration] Context impl PostgresqlImpl." >&2; printf '%b' "$CURRENT" ;;
  *"alembic heads") printf '%b' "$HEADS" ;;
  "compose logs "*) printf '%b' "$LOGS" ;;
  *) exit 1 ;;
esac
SH
chmod +x "$dir/docker"
export DOCKER=$dir/docker

healthy() {
  export PS='caddy ghcr.io/rakin-app/rakin-web:v2\napi ghcr.io/rakin-app/rakin-api:v2\njobs ghcr.io/rakin-app/rakin-api:v2\npostgres postgres:17\n'
  export CURRENT='0079 (head)\n' HEADS='0079 (head)\n'
  export LOGS='api-1  | {"ts": "t", "level": "INFO", "logger": "app.request", "message": "GET /healthz"}\n'
}
healthy
printf 'SECRET_KEY=s\nRAKIN_TAG=v2\n' >"$dir/.env"
printf '2026-11-18T00:00:00Z\tdeploy\tv1\t-\n2026-11-18T01:00:00Z\tdeploy\tv2\tv1\n' >"$dir/releases.log"
staging_env() { printf 'SECRET_KEY=s\nSEED_ONLY=1\nRAKIN_TAG=v2\n' >"$dir/.env"; }
production_env() { printf 'SECRET_KEY=s\nRAKIN_TAG=v2\n' >"$dir/.env"; }

fails=0
check() { # check <description> <command...>
  local what=$1; shift
  if "$@"; then echo "ok   - $what"; else echo "FAIL - $what"; fails=1; fi
}
run() { : >"$dir/calls"; "$dir/verify.sh" "$@" >"$dir/out" 2>&1; }
refused() { ! run "$@"; }
said() { grep -qF -- "$1" "$dir/out"; }
not_said() { ! said "$1"; }
not_called() { ! grep -qF -- "$1" "$dir/calls"; }

check "refuses no arguments" refused
check "refuses an unknown environment" refused prod v2
check "refuses a tag that is not an image tag" refused production "v2;rm -rf /"

production_env
check "production passes a healthy release" run production v2
check "names each check it passed" said "ok   - alembic current is the release's head (0079)"
staging_env
check "staging passes a healthy release" run staging v2

# 1. The host is the environment's.
production_env
check "staging refuses a host without SEED_ONLY=1" refused staging v2
check "and says it is not staging's host" said "not staging's host"
staging_env
check "production refuses a host with SEED_ONLY=1" refused production v2
check "and says it is not production's host" said "not production's host"
printf 'SEED_ONLY="true"\n' >"$dir/.env"
check "SEED_ONLY is read as the app reads a boolean" run --check-host staging
printf 'SEED_ONLY=0\n' >"$dir/.env"
check "SEED_ONLY=0 is not seed-only" refused --check-host staging
check "--check-host passes production without SEED_ONLY" run --check-host production
check "--check-host asks docker nothing" not_called "compose"
rm "$dir/.env"
check "refuses a directory without .env" refused --check-host production
production_env

# 2. What runs.
PS='caddy ghcr.io/rakin-app/rakin-web:v2\napi ghcr.io/rakin-app/rakin-api:v1\njobs ghcr.io/rakin-app/rakin-api:v2\n' \
  check "refuses a service on another tag" refused production v2
check "names the service and its image" said "api runs ghcr.io/rakin-app/rakin-api:v1, not :v2"
PS='caddy ghcr.io/rakin-app/rakin-web:v2\napi ghcr.io/rakin-app/rakin-api:v2\n' \
  check "refuses a stopped service" refused production v2
check "names the stopped service" said "jobs is not running"
PS='caddy ghcr.io/rakin-app/rakin-web:v22\napi ghcr.io/rakin-app/rakin-api:v22\njobs ghcr.io/rakin-app/rakin-api:v22\n' \
  check "a tag is matched whole, not as a prefix" refused production v2
PS='caddy ghcr.io/rakin-app/rakin-web:v1x2\napi ghcr.io/rakin-app/rakin-api:v1.2\njobs ghcr.io/rakin-app/rakin-api:v1.2\n' \
  check "a tag's dots are matched as dots" refused production v1.2

# 3. The schema.
CURRENT='0078\n' check "refuses a database behind the release's head" refused production v2
check "names both revisions" said "alembic current is '0078', the release's head is '0079'"
CURRENT='' check "refuses when alembic current prints nothing" refused production v2
HEADS='' check "refuses when alembic heads prints nothing" refused production v2
CURRENT='0079a (head)\n0079b (head)\n' HEADS='0079b (head)\n0079a (head)\n' \
  check "two heads match in any order" run production v2
CURRENT='0080 (head)\n' PS='caddy ghcr.io/rakin-app/rakin-web:v1\napi ghcr.io/rakin-app/rakin-api:v1\njobs ghcr.io/rakin-app/rakin-api:v1\n' \
  check "a rollback does not compare the schema" run --rollback production v1
check "and says so" said "skip - alembic current"
check "a rollback asks Alembic nothing" not_called "alembic"

# 4. Errors since the restart.
LOGS='api-1  | {"ts": "t", "level": "ERROR", "logger": "app.mail", "message": "send failed for ana@example.com"}\njobs-1  | {"ts": "t", "level": "ERROR", "logger": "app.jobs", "message": "x"}\napi-1  | {"ts": "t", "level": "ERROR", "logger": "app.mail", "message": "y"}\n' \
  check "refuses an ERROR in the logs" refused production v2
check "counts them by logger" said "3 ERROR line(s) from api or jobs in the last 5m (app.jobs x1, app.mail x2)"
check "never prints a log message" not_said "ana@example.com"
LOGS='api-1  | {"ts": "t", "level": "WARNING", "logger": "app.mail", "message": "slow"}\n' \
  check "a WARNING passes" run production v2
VERIFY_LOG_SINCE=10m check "the window can be widened" run production v2
check "and is the one asked for" grep -q -- "--since 10m api jobs" "$dir/calls"

# The rollback line.
CURRENT='0078\n' check "a failure ends with the rollback line" refused production v2
check "the rollback line names the release before this one" said "rollback: ./deploy.sh --rollback v1"
check "--rollback-line prints it alone" run --rollback-line v2
check "--rollback-line's output" [ "$(cat "$dir/out")" = "rollback: ./deploy.sh --rollback v1" ]
check "a first release has nothing to go back to" run --rollback-line v1
check "and says so" said "names no release before v1"
check "a passing run prints no rollback line" run production v2
check "(none printed)" not_said "rollback:"

# Piped to `bash -s` in the directory, as the workflow runs check 1.
staging_env
check "--check-host works piped to bash -s" sh -c "cd '$dir' && bash -s -- --check-host staging <'$src/verify.sh' >/dev/null"

exit "$fails"
