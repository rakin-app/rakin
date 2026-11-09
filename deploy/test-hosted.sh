#!/usr/bin/env bash
# Boot the hosted stack from images built here, the way deploy.sh runs it
# (migrate, then up), and smoke-test it. CI runs this on every PR, so a
# release is never the first time the images, Caddyfile and hosted Compose
# file meet. Needs Docker and port 80; the stack is removed afterwards.
#
# Caddy serves plain HTTP on :80 here (SITE_ADDRESS=:80): no certificate,
# no DNS. Object storage and SES are configured but never reached.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
export RAKIN_TAG=test
docker build -q -t "ghcr.io/rakin-app/rakin-api:$RAKIN_TAG" "$root/backend" >/dev/null
docker build -q -t "ghcr.io/rakin-app/rakin-web:$RAKIN_TAG" -f "$root/deploy/web.Dockerfile" "$root" >/dev/null

dir=$(mktemp -d)
cp "$root/deploy/docker-compose.yml" "$dir/"
# deploy/.env.example with its placeholders filled in.
sed \
	-e 's|^SITE_ADDRESS=.*|SITE_ADDRESS=:80|' \
	-e 's|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=http://localhost|' \
	-e 's|^SENTRY_DSN=.*|SENTRY_DSN=|' \
	-e 's|^S3_ENDPOINT_URL=.*|S3_ENDPOINT_URL=http://s3.invalid|' \
	-e 's|^S3_PUBLIC_ENDPOINT_URL=.*|S3_PUBLIC_ENDPOINT_URL=http://s3.invalid|' \
	-e 's|=<.*>$|=test-only-0123456789abcdef0123456789abcdef|' \
	"$root/deploy/.env.example" >"$dir/.env"
if grep -n '<' "$dir/.env" | grep -v '^[0-9]*:#' | grep -v '^[0-9]*:MAIL_FROM='; then
	echo "test-hosted: a placeholder is left in .env" >&2
	exit 1
fi

compose() { docker compose --project-directory "$dir" -p rakin-hosted-test "$@"; }
cleanup() {
	status=$?
	[ $status = 0 ] || compose logs --no-color --tail 50 || true
	compose --profile migrate down -v --remove-orphans >/dev/null 2>&1 || true
	rm -rf "$dir"
	exit $status
}
trap cleanup EXIT

compose run --rm migrate
compose up -d --wait --wait-timeout 180
"$root/deploy/smoke.sh" http://localhost
