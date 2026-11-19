#!/usr/bin/env bash
# Is this host running the release it was given? Lives in /srv/rakin beside
# deploy.sh; the deploy workflow runs it over SSH after deploy.sh, then runs
# smoke.sh from the runner.
#
#   ./verify.sh production v1.4.0              # after ./deploy.sh v1.4.0
#   ./verify.sh --rollback staging v1.3.2      # after ./deploy.sh --rollback v1.3.2
#   ./verify.sh --check-host staging           # only: is this staging's host?
#   ./verify.sh --rollback-line v1.4.0         # only: how to go back from v1.4.0
#
# Checks, in order:
#  1. the host is the environment's: staging's `.env` has SEED_ONLY=1 and
#     production's does not, so a swapped host, `.env` or secret stops here;
#  2. caddy, api and jobs run, and every running rakin-app image is :<tag>;
#  3. `alembic current` in the api equals that image's `alembic heads` (not
#     after a rollback: an older image does not know the newer revisions);
#  4. the api and jobs logged no ERROR in the last VERIFY_LOG_SINCE (5m).
# Any failure exits non-zero and ends with the rollback line for this host.
# The workflow runs check 1 alone before it backs up or deploys, by piping
# this script to `bash -s` in /srv/rakin.
set -euo pipefail

usage() {
	echo "usage: $0 [--rollback] <staging|production> <tag>" >&2
	echo "       $0 --check-host <staging|production>" >&2
	echo "       $0 --rollback-line <tag>" >&2
	exit 2
}
is_tag() { [[ $1 =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]]; }

# Under `bash -s`, $0 is `bash` and its dirname `.`: the caller's directory.
cd "$(dirname "$0")"
docker=${DOCKER:-docker}

# The line that takes this host back to the release before <tag>, from the
# releases.log deploy.sh appends to (time, kind, tag, previous).
# After a rollback to <tag>, that is the release it rolled back from.
rollback_line() {
	local previous
	previous=$(awk -F '\t' -v tag="$1" '$3 == tag { prev = $4 } END { print prev }' releases.log 2>/dev/null || true)
	if is_tag "${previous:-}"; then
		echo "rollback: ./deploy.sh --rollback $previous"
	else
		echo "rollback: releases.log names no release before $1; nothing to go back to"
	fi
}

# SEED_ONLY's value in .env, as the app reads a boolean: 1/true/yes/on is set.
seed_only() {
	local value
	value=$(sed -n 's/^SEED_ONLY=//p' .env | tail -n 1 | tr -d "\"' " | tr '[:upper:]' '[:lower:]')
	case $value in 1 | true | yes | on) return 0 ;; *) return 1 ;; esac
}

fails=0
ok() { echo "ok   - $1"; }
fail() { echo "FAIL - $1"; fails=1; }

check_host() { # check_host <environment>
	[ -f .env ] || { fail "no .env in $PWD"; return; }
	case $1 in
		staging)
			if seed_only; then ok "staging's .env has SEED_ONLY=1"; else
				fail "this is not staging's host: .env lacks SEED_ONLY=1 (a production host, or production's secrets in the staging environment?)"
			fi ;;
		production)
			if seed_only; then
				fail "this is not production's host: .env has SEED_ONLY=1 (the staging host, or staging's secrets in the production environment?)"
			else ok "production's .env has no SEED_ONLY"; fi ;;
	esac
}

case ${1:-} in
	--rollback-line)
		{ [ $# -eq 2 ] && is_tag "$2"; } || usage
		rollback_line "$2"
		exit 0 ;;
	--check-host)
		[ $# -eq 2 ] || usage
		case $2 in staging | production) ;; *) usage ;; esac
		check_host "$2"
		exit "$fails" ;;
esac

rollback=0
if [ "${1:-}" = "--rollback" ]; then rollback=1; shift; fi
[ $# -eq 2 ] || usage
environment=$1 tag=$2
case $environment in staging | production) ;; *) usage ;; esac
is_tag "$tag" || { echo "verify: bad tag '$tag'" >&2; exit 2; }

check_host "$environment"

# 2. What runs. `ps` lists running containers only, so a stopped service is
# missing rather than wrong.
running=$("$docker" compose ps --format '{{.Service}} {{.Image}}' 2>&1) || {
	fail "docker compose ps failed: $running"
	running=
}
for service in caddy api jobs; do
	grep -q "^$service " <<<"$running" || fail "$service is not running"
done
wrong=$(awk -v want=":$tag" '
	$2 ~ /^ghcr\.io\/rakin-app\// && substr($2, length($2) - length(want) + 1) != want { print $1 " runs " $2 }
' <<<"$running")
if [ -n "$running" ] && [ -z "$wrong" ]; then
	ok "every rakin-app service runs :$tag"
elif [ -n "$wrong" ]; then
	while read -r line; do fail "$line, not :$tag"; done <<<"$wrong"
fi

# 3. The schema. Revisions are the first word of each line on stdout; Alembic
# logs to stderr.
revisions() { "$docker" compose exec -T api alembic "$1" 2>/dev/null | awk 'NF { print $1 }' | sort | paste -sd ' ' -; }
if [ $rollback = 1 ]; then
	echo "skip - alembic current: a rollback keeps the newer schema"
else
	current=$(revisions current || true)
	heads=$(revisions heads || true)
	if [ -z "$heads" ]; then
		fail "alembic heads printed nothing in the api"
	elif [ "$current" = "$heads" ]; then
		ok "alembic current is the release's head ($heads)"
	else
		fail "alembic current is '${current:-nothing}', the release's head is '$heads'"
	fi
fi

# 4. Errors since the restart. Only the count and the loggers are printed:
# a message can hold a member's data, and the workflow's log is public.
since=${VERIFY_LOG_SINCE:-5m}
errors=$("$docker" compose logs --no-color --since "$since" api jobs 2>&1 | grep -F '"level": "ERROR"' || true)
if [ -z "$errors" ]; then
	ok "no ERROR logged by api or jobs in the last $since"
else
	loggers=$(grep -o '"logger": "[^"]*"' <<<"$errors" | sed 's/"logger": //; s/"//g' | sort | uniq -c | awk '{ printf "%s%s x%s", sep, $2, $1; sep = ", " }')
	fail "$(grep -c . <<<"$errors") ERROR line(s) from api or jobs in the last $since (${loggers:-no logger}); read them on the host: docker compose logs --since $since api jobs"
fi

if [ $fails != 0 ]; then
	echo "verify: $tag on $environment failed a check"
	rollback_line "$tag"
fi
exit "$fails"
