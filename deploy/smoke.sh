#!/usr/bin/env bash
# Is a running stack serving? Run after every deploy, and by CI against a
# stack booted from freshly built images (deploy/test-hosted.sh).
#
#   deploy/smoke.sh https://staging.rakin.app
#
# Checks what Caddy and the api do together: /healthz reaches Postgres, the
# SPA is served on / and on a client-side route, and /api reaches the api.
# It signs nobody in and uploads nothing; docs/deploy.md has the browser
# upload check.
set -euo pipefail

base=${1:?usage: $0 <base-url>}
base=${base%/}
fails=0

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

expect() { # expect <description> <path> <status> [<body substring>]
	local got body
	got=$(curl -sS --max-time 15 -o "$tmp" -w '%{http_code}' "$base$2") || got=000
	body=$(cat "$tmp")
	if [ "$got" = "$3" ] && { [ -z "${4:-}" ] || [[ $body == *"$4"* ]]; }; then
		echo "ok   - $1"
	else
		echo "FAIL - $1 ($2: got $got, want $3${4:+ with \"$4\"})"
		fails=1
	fi
}

expect "healthz: the api answers and reaches Postgres" /healthz 200 '"database":"ok"'
expect "the SPA is served" / 200 '<div id="root">'
expect "a client-side route gets the SPA" /alumnos 200 '<div id="root">'
# The bundle index.html names is served as itself, not as the SPA fallback.
asset=$(grep -o '/assets/[^"]*\.js' "$tmp" | head -n 1 || true)
type=$(curl -sS --max-time 15 -o /dev/null -w '%{http_code} %{content_type}' "$base${asset:-/assets/missing.js}") || type=000
if [[ $type == "200 text/javascript"* ]]; then
	echo "ok   - the SPA's script is served as JavaScript"
else
	echo "FAIL - the SPA's script is served as JavaScript (${asset:-no /assets/*.js in index.html}: got $type)"
	fails=1
fi
expect "/api reaches the api, which wants a session" /api/me/role 401

exit "$fails"
