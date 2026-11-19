#!/usr/bin/env bash
# Tests for reset-staging.sh, with a fake `docker` that records its calls, as
# test-deploy.sh does. Its psql answers: the database exists unless
# DB_EXISTS is empty, it has a gym table unless GYM_TABLE is empty, and the
# gyms in it are GYMS. A call containing FAIL_ON fails.
# The checks are functions that `check` calls by name:
# shellcheck disable=SC2329
set -euo pipefail

src=$(cd "$(dirname "$0")" && pwd)
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
cp "$src/reset-staging.sh" "$dir/"
cat >"$dir/docker" <<'SH'
#!/usr/bin/env bash
echo "$*" >>"$(dirname "$0")/calls"
if [ -n "${FAIL_ON:-}" ] && [[ "$*" == *"$FAIL_ON"* ]]; then exit 1; fi
case $* in
  *"FROM pg_database"*) echo "${DB_EXISTS-1}" ;;
  *to_regclass*) echo "${GYM_TABLE-gym}" ;;
  *"SELECT slug FROM gym"*) for g in ${GYMS-academia-sur}; do echo "$g"; done ;;
esac
SH
cat >"$dir/smoke.sh" <<'SH'
#!/usr/bin/env bash
echo "smoke $*" >>"$(dirname "$0")/calls"
[ -z "${SMOKE_FAILS:-}" ]
SH
cat >"$dir/crontab" <<'SH'
#!/usr/bin/env bash
tab=$(dirname "$0")/tab
if [ "$1" = -l ]; then cat "$tab" 2>/dev/null; else cat >"$tab.new" && mv "$tab.new" "$tab"; fi
SH
mkdir "$dir/bin"
cat >"$dir/bin/date" <<'SH'
#!/usr/bin/env bash
if [ "$*" = +%H ]; then echo "${HOUR:?}"; else exec /bin/date "$@"; fi
SH
chmod +x "$dir/docker" "$dir/smoke.sh" "$dir/crontab" "$dir/bin/date"
export DOCKER=$dir/docker CRONTAB=$dir/crontab PATH="$dir/bin:$PATH"

fails=0
check() { # check <description> <command...>
  local what=$1; shift
  if "$@"; then echo "ok   - $what"; else echo "FAIL - $what"; fails=1; fi
}
run() { : >"$dir/calls"; : >"$dir/reset.log"; "$dir/reset-staging.sh" "$@" >"$dir/out" 2>&1; }
refused() { ! run "$@"; }
called() { grep -q -- "$1" "$dir/calls"; }
not_called() { ! called "$1"; }
nothing_called() { [ ! -s "$dir/calls" ]; }
line_of() { grep -n -- "$1" "$dir/calls" | head -n 1 | cut -d: -f1; }
in_order() { # in_order <call>...: each first appears after the one before
  local prev=0 n
  for c in "$@"; do
    n=$(line_of "$c"); [ -n "$n" ] && [ "$n" -gt "$prev" ] || return 1; prev=$n
  done
}
said() { grep -q -- "$1" "$dir/out"; }
logged() { grep -q -- "$1" "$dir/reset.log"; }
env_file() { printf '%s\n' 'MAIL_FROM=Rakin <no-reply@rakin.app>' 'PUBLIC_BASE_URL=https://stage.test' 'POSTGRES_USER=rakin' 'POSTGRES_DB=rakin' "$@" >"$dir/.env"; }

check "the seed slugs are the seed's (backend/app/seed/data.py)" \
  [ "$(sed -n 's/^SEED_SLUGS=(\(.*\))$/\1/p' "$src/reset-staging.sh")" = \
    "$(sed -n 's/^GYM_SLUG = "\(.*\)"$/\1/p' "$src/../backend/app/seed/data.py")" ]

check "refuses to run without .env" refused
env_file
check "refuses without SEED_ONLY" refused
check "says why" said "SEED_ONLY=1"
check "touches nothing then" nothing_called
env_file SEED_ONLY=false
check "refuses with SEED_ONLY=false" refused
check "refuses an unknown argument" refused --now
env_file SEED_ONLY=1 'STAGING_OPERATORS=pm@rakin.app, owner@rakin.app'

GYMS="academia-sur meta" check "refuses when a gym is not the seed's" refused
check "names that gym" said "not the seed's: meta"
check "stops nothing then" not_called "stop"
check "drops nothing then" not_called "DROP DATABASE"
check "the refusal is in reset.log" logged "refusing"
FAIL_ON=to_regclass check "a failed check refuses" refused
check "and drops nothing" not_called "DROP DATABASE"
check "and says nothing was stopped" said "nothing was stopped or dropped"

check "resets a seed-only database" run
check "the steps run in order" in_order "up -d --wait postgres" "stop api jobs caddy" \
  'DROP DATABASE IF EXISTS "rakin" WITH (FORCE)' 'CREATE DATABASE "rakin"' \
  "compose --profile migrate run --rm migrate" "run --rm api python -m app.seed" \
  "app.operators grant" "up -d --wait --remove-orphans" "smoke https://stage.test"
check "the database is dropped as the superuser, from postgres" called "psql -U rakin -d postgres"
check "every operator is granted" in_order \
  "grant --email pm@rakin.app --name pm" "grant --email owner@rakin.app --name owner"
check "the run is in reset.log" logged "done: academia-sur reseeded, 2 operator(s) granted"

DB_EXISTS='' check "resets when the database is missing" run
check "without asking it for gyms" not_called "SELECT slug FROM gym"
GYM_TABLE='' check "resets when the database has no gym table yet" run
GYMS='' check "resets an empty database" run

env_file SEED_ONLY=true
run
check "no STAGING_OPERATORS grants nobody" not_called "app.operators"
check "and says so" logged "0 operator(s) granted"

FAIL_ON=app.seed check "a failed seed fails the reset" refused
check "and starts nothing after it" not_called "up -d --wait --remove-orphans"
check "and says where it stopped" said "failed while seeding; staging may be down"
SMOKE_FAILS=1 check "a failed smoke fails the reset" refused

HOUR=14 run --cron
check "--cron outside the 05:00 hour does nothing" nothing_called
HOUR=05 run --cron
check "--cron in the 05:00 hour resets" called "smoke https://stage.test"

"$dir/reset-staging.sh" --install-cron >/dev/null
echo "30 2 * * * /usr/bin/true" >>"$dir/tab"
"$dir/reset-staging.sh" --install-cron >/dev/null
check "--install-cron adds the hourly line once" \
  [ "$(grep -c "^0 \* \* \* \* $dir/reset-staging.sh --cron" "$dir/tab")" = 1 ]
check "--install-cron keeps the other lines" grep -q /usr/bin/true "$dir/tab"
env_file
rm -f "$dir/tab"
check "--install-cron refuses without SEED_ONLY" refused --install-cron
check "and installs nothing" [ ! -e "$dir/tab" ]

exit "$fails"
