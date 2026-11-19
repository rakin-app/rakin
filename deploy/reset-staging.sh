#!/usr/bin/env bash
# Put the staging host back to fresh seed data (#464 §6). Lives in /srv/rakin
# beside docker-compose.yml and .env; the deploy copies it there with the
# other scripts, and the deploy user's crontab runs it every night at 05:00
# America/Santiago, which keeps the seed's dates current and undoes the
# day's tests.
#
#   ./reset-staging.sh                  # reset now
#   ./reset-staging.sh --cron           # what the crontab runs, every hour:
#                                       # resets only in the 05:00 hour, Santiago time
#   ./reset-staging.sh --install-cron   # once, on the staging host: add that line
#
# It refuses unless .env has SEED_ONLY=1, and refuses if the database holds
# any gym that is not the seed's: whatever host it lands on, it never drops a
# real gym. Then it stops api, jobs and caddy, drops and recreates the
# database, bootstraps and migrates it (the `migrate` one-shot), loads the
# seed, grants platform operator to every address in STAGING_OPERATORS
# (comma-separated, in .env), starts everything and runs smoke.sh. Every run,
# refusals included, is appended to reset.log. It holds deploy.lock, as
# deploy.sh does, so a reset and a deploy never run together.
set -Eeuo pipefail

# The seed's gyms (backend/app/seed/data.py, GYM_SLUG); test-reset-staging.sh
# fails if the two drift apart.
SEED_SLUGS=(academia-sur)
# The hour, in this zone, a --cron run resets in. Cron itself runs in the
# host's zone (UTC), and Ubuntu's cron has no CRON_TZ, so the crontab runs
# this hourly and the check is here: it follows Chile's clock changes.
RESET_TZ=America/Santiago
RESET_HOUR=05
CRON_LINE="0 * * * * $(cd "$(dirname "$0")" && pwd)/$(basename "$0") --cron >/dev/null 2>&1"

mode=now
case ${1:-} in
	"") ;;
	--cron) mode=cron ;;
	--install-cron) mode=install ;;
	*) mode=bad ;;
esac
[ $# -le 1 ] || mode=bad

cd "$(dirname "$0")"
docker=${DOCKER:-docker}
crontab=${CRONTAB:-crontab}
flock=${FLOCK:-flock}

# The other 23 hourly runs are not runs at all: nothing to log.
if [ $mode = cron ] && [ "$(TZ=$RESET_TZ date +%H)" != $RESET_HOUR ]; then
	exit 0
fi

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) reset: $*"; }
# A refusal goes to reset.log like everything else: --cron sends stdout and
# stderr to /dev/null, so the log is the only place a refused night shows.
refuse() { log "refusing: $*"; exit "${refusal_status:-1}"; }
# .env is read, never sourced: values such as MAIL_FROM hold `<` and spaces.
env_of() { sed -n "s/^$1=//p" .env | tail -n 1; }

reset() {
	[ $mode != bad ] || { refusal_status=2; refuse "usage: $0 [--cron | --install-cron]"; }
	[ -f .env ] || refuse "no .env in $PWD"
	seed_only=$(env_of SEED_ONLY | tr '[:upper:]' '[:lower:]')
	case $seed_only in
		1 | true | yes | on) ;;
		*) refuse ".env has no SEED_ONLY=1, so this is not the staging host" ;;
	esac

	if [ $mode = install ]; then
		{ "$crontab" -l 2>/dev/null | grep -vF "$(basename "$0") --cron" || true; echo "$CRON_LINE"; } | "$crontab" -
		log "crontab runs $CRON_LINE"
		return 0
	fi

	# One at a time with deploy.sh, which takes the same lock: a deploy that
	# lands mid-reset would migrate a database being dropped.
	exec 9>>deploy.lock
	"$flock" -w "${LOCK_WAIT_SECONDS:-600}" 9 || refuse "a deploy holds $PWD/deploy.lock"

	ident='^[A-Za-z_][A-Za-z0-9_]{0,62}$'
	pg_user=$(env_of POSTGRES_USER); pg_user=${pg_user:-rakin}
	pg_db=$(env_of POSTGRES_DB); pg_db=${pg_db:-rakin}
	[[ $pg_user =~ $ident && $pg_db =~ $ident ]] || refuse "odd POSTGRES_USER or POSTGRES_DB in .env"
	base_url=$(env_of PUBLIC_BASE_URL)
	[ -n "$base_url" ] || refuse ".env has no PUBLIC_BASE_URL to smoke-test"
	operators=$(env_of STAGING_OPERATORS | tr -d ' ')

	compose() { "$docker" compose "$@"; }
	psql_in() { # psql_in <database> <sql>: one value per line
		compose exec -T postgres psql -U "$pg_user" -d "$1" -v ON_ERROR_STOP=1 -tA -c "$2"
	}

	stage=checking
	# shellcheck disable=SC2329 # the ERR trap calls it
	on_failure() {
		if [ "$stage" = checking ]; then
			log "failed while $stage; nothing was stopped or dropped"
		else
			log "failed while $stage; staging may be down: read the lines above, then run $PWD/reset-staging.sh again"
		fi
	}
	trap on_failure ERR

	log "start"
	compose up -d --wait postgres

	# A database that is missing, or has no gym table yet (a reset that failed
	# halfway), holds no gym to protect.
	# Each query on a line of its own, so a failing one stops here (set -e).
	gyms='' table=''
	exists=$(psql_in postgres "SELECT 1 FROM pg_database WHERE datname = '$pg_db'")
	if [ -n "$exists" ]; then table=$(psql_in "$pg_db" "SELECT to_regclass('public.gym')"); fi
	if [ -n "$table" ]; then gyms=$(psql_in "$pg_db" "SELECT slug FROM gym ORDER BY slug"); fi
	foreign=
	for slug in $gyms; do
		seed=0
		for s in "${SEED_SLUGS[@]}"; do [ "$slug" = "$s" ] && seed=1; done
		[ $seed = 1 ] || foreign="$foreign $slug"
	done
	[ -z "$foreign" ] || refuse "the database holds gyms that are not the seed's:$foreign"

	stage=stopping
	compose stop api jobs caddy
	stage="recreating the database"
	psql_in postgres "DROP DATABASE IF EXISTS \"$pg_db\" WITH (FORCE)" >/dev/null
	psql_in postgres "CREATE DATABASE \"$pg_db\"" >/dev/null
	stage=migrating
	compose --profile migrate run --rm migrate
	stage=seeding
	compose run --rm api python -m app.seed
	stage="granting operators"
	granted=0
	for email in ${operators//,/ }; do
		compose run --rm api python -m app.operators grant --email "$email" --name "${email%%@*}"
		granted=$((granted + 1))
	done
	stage=starting
	# No --profile, as in deploy.sh: it would replace .env's COMPOSE_PROFILES.
	compose up -d --wait --remove-orphans
	stage="smoke-testing"
	./smoke.sh "$base_url"

	trap - ERR
	log "done: ${SEED_SLUGS[*]} reseeded, $granted operator(s) granted"
}

# Into reset.log, and to whoever ran it.
reset 2>&1 | tee -a reset.log
exit "${PIPESTATUS[0]}"
