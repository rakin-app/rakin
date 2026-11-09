#!/usr/bin/env bash
# Run a release on this host. Lives in /srv/rakin beside docker-compose.yml
# and .env; the deploy workflow copies both scripts and runs it over SSH.
#
#   ./deploy.sh v1.4.0              # pull, migrate, restart on v1.4.0
#   ./deploy.sh --rollback v1.3.2   # pull, restart on v1.3.2; no migrations
#
# A deploy migrates before anything restarts, so a failed migration leaves
# the running release untouched. A rollback never migrates: migrations are
# additive within a release, so the previous image runs on the newer schema,
# and its Alembic would refuse a revision it does not know. On success the
# tag is written to .env as RAKIN_TAG, so a plain `docker compose ...` here
# targets the live release, and appended to releases.log.
set -Eeuo pipefail  # -E: the ERR trap fires inside compose() too

usage() { echo "usage: $0 [--rollback] <tag>" >&2; exit 2; }

rollback=0
if [ "${1:-}" = "--rollback" ]; then rollback=1; shift; fi
[ $# -eq 1 ] || usage
tag=$1
# An image tag, nothing a shell or sed would read as more than a word.
is_tag() { [[ $1 =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]]; }
is_tag "$tag" || { echo "deploy: bad tag '$tag'" >&2; exit 2; }

cd "$(dirname "$0")"
[ -f .env ] || { echo "deploy: no .env in $PWD (see deploy/.env.example)" >&2; exit 1; }
docker=${DOCKER:-docker}

previous=$(sed -n 's/^RAKIN_TAG=//p' .env | tail -n 1)
# Before the first deploy it is still .env.example's `<placeholder>`: no release.
is_tag "$previous" || previous=
# The shell's value wins over .env for Compose's interpolation.
export RAKIN_TAG=$tag
compose() { "$docker" compose --profile migrate "$@"; }

restarting=0
on_failure() {
	if [ $restarting = 0 ]; then
		echo "deploy: $tag failed before any restart; ${previous:-the old release} still runs" >&2
	else
		echo "deploy: $tag failed while restarting; .env still names ${previous:-no release}" >&2
		if [ -n "$previous" ] && [ "$previous" != "$tag" ]; then
			echo "deploy: to go back: $0 --rollback $previous" >&2
		fi
	fi
}
trap on_failure ERR

echo "deploy: ${previous:-nothing} -> $tag$([ $rollback = 1 ] && echo ' (rollback)')"
compose pull --quiet
if [ $rollback = 0 ]; then
	compose run --rm migrate
fi
# `migrate` is a one-shot under its own profile, so `up` leaves it alone.
restarting=1
"$docker" compose up -d --wait --remove-orphans

trap - ERR
# Rewrite RAKIN_TAG in place, keeping .env's mode and owner.
tmp=$(mktemp)
{ grep -v '^RAKIN_TAG=' .env || true; echo "RAKIN_TAG=$tag"; } >"$tmp"
cat "$tmp" >.env
rm -f "$tmp"
printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
	"$([ $rollback = 1 ] && echo rollback || echo deploy)" "$tag" "${previous:--}" >>releases.log
# Untagged layers only: earlier releases stay pulled, so a rollback is fast.
# Best-effort: the release is live and recorded by now.
"$docker" image prune -f >/dev/null || echo "deploy: image prune failed; ignored" >&2
echo "deploy: $tag is live"
