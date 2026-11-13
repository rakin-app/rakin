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

# smoke.sh, against a fake `curl` that fails the handshake (exit 35) for its
# first $TLS_FAILS calls, then serves a healthy stack, with /healthz
# answering $HEALTHZ with $HEALTHZ_BODY.
mkdir "$dir/bin"
cat >"$dir/bin/curl" <<'SH'
#!/usr/bin/env bash
n=$(($(cat "$(dirname "$0")/n" 2>/dev/null || echo 0) + 1))
echo "$n" >"$(dirname "$0")/n"
[ "$n" -gt "${TLS_FAILS:-0}" ] || { echo "curl: (35) TLS connect error" >&2; exit 35; }
out=/dev/null fmt= url=
while [ $# -gt 0 ]; do
  case $1 in -o) out=$2; shift ;; -w) fmt=$2; shift ;; -*) ;; *) url=$1 ;; esac
  shift
done
case $url in
  */healthz) code=${HEALTHZ:-200}; body=${HEALTHZ_BODY:-'{"database":"ok"}'} ;;
  */api/*) code=401; body= ;;
  */assets/*) code=200; body= ;;
  *) code=200; body='<div id="root"></div><script src="/assets/index.js"></script>' ;;
esac
printf '%s' "$body" >"$out"
[[ $fmt == *content_type* ]] && printf '%s text/javascript' "$code" || printf '%s' "$code"
SH
chmod +x "$dir/bin/curl"
smoke() { rm -f "$dir/bin/n"; PATH="$dir/bin:$PATH" SMOKE_RETRY_SECONDS=0 "$src/smoke.sh" https://stage.test >"$dir/out" 2>&1; }
refused_smoke() { ! smoke; }

check "smoke passes a healthy stack" smoke
check "a healthy stack is not waited for" not_said "waiting for TLS"
TLS_FAILS=3 check "smoke waits for a certificate that arrives" smoke
check "the wait is announced once" [ "$(grep -c 'waiting for TLS on https://stage.test' "$dir/out")" = 1 ]
HEALTHZ=503 check "a 503 still fails smoke" refused_smoke
check "a 503 is not waited for" not_said "waiting for TLS"
HEALTHZ_BODY='{"database":"down"}' check "a wrong /healthz body still fails smoke" refused_smoke
check "a wrong body is not waited for" not_said "waiting for TLS"
TLS_FAILS=1000 SMOKE_TLS_WAIT=0 check "smoke gives up on a certificate that never arrives" refused_smoke

exit "$fails"
