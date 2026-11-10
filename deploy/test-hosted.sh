#!/usr/bin/env bash
# Boot the hosted stack from images built here, the way deploy.sh runs it
# (migrate, then up), and smoke-test it. CI runs this on every PR, so a
# release is never the first time the images, Caddyfile and hosted Compose
# file meet. Needs Docker and port 80; the stack is removed afterwards.
#
# Caddy serves plain HTTP on :80 here (SITE_ADDRESS=:80): no certificate,
# no DNS. Object storage and mail (Resend) are configured but never reached.
# Backups are: a Garage beside the stack stands in for their R2 bucket, and
# a backup of a gym is restored with deploy/restore.sh and checked.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
export RAKIN_TAG=test
docker build -q -t "ghcr.io/rakin-app/rakin-api:$RAKIN_TAG" "$root/backend" >/dev/null
docker build -q -t "ghcr.io/rakin-app/rakin-web:$RAKIN_TAG" -f "$root/deploy/web.Dockerfile" "$root" >/dev/null

dir=$(mktemp -d)
cp "$root/deploy/docker-compose.yml" "$dir/"

# The backups' key pair, made here as it would be on a laptop.
identity=$(docker run --rm "ghcr.io/rakin-app/rakin-api:$RAKIN_TAG" age-keygen 2>/dev/null)
recipient=$(sed -n 's/^# public key: //p' <<<"$identity")
# Garage's own key format: GK and 24 hex digits, a 64-digit secret.
garage_key=GK0123456789abcdef01234567
garage_secret=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

# The backup bucket's stand-in, in the stack's network as `garage`.
cat >"$dir/garage.yml" <<YML
services:
  garage:
    image: dxflrs/garage:v2.5.0
    environment:
      GARAGE_RPC_SECRET: $garage_secret
    volumes:
      - $root/garage/garage.toml:/etc/garage.toml:ro
      - garage_meta:/var/lib/garage/meta
      - garage_data:/var/lib/garage/data
  garage-init:
    build: $root/garage
    profiles: ["garage-init"]
    environment:
      GARAGE_RPC_SECRET: $garage_secret
      S3_BUCKET: rakin-backups
      S3_ACCESS_KEY_ID: $garage_key
      S3_SECRET_ACCESS_KEY: $garage_secret
    volumes:
      - garage_meta:/var/lib/garage/meta:ro
    depends_on:
      - garage
volumes:
  garage_meta:
  garage_data:
YML
# deploy/.env.example with its placeholders filled in.
sed \
	-e 's|^SITE_ADDRESS=.*|SITE_ADDRESS=:80|' \
	-e 's|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=http://localhost|' \
	-e 's|^SENTRY_DSN=.*|SENTRY_DSN=|' \
	-e 's|^S3_ENDPOINT_URL=.*|S3_ENDPOINT_URL=http://s3.invalid|' \
	-e 's|^S3_PUBLIC_ENDPOINT_URL=.*|S3_PUBLIC_ENDPOINT_URL=http://s3.invalid|' \
	-e "s|^BACKUP_AGE_RECIPIENT=.*|BACKUP_AGE_RECIPIENT=$recipient|" \
	-e 's|^BACKUP_S3_ENDPOINT_URL=.*|BACKUP_S3_ENDPOINT_URL=http://garage:3900|' \
	-e 's|^BACKUP_S3_REGION=.*|BACKUP_S3_REGION=garage|' \
	-e "s|^BACKUP_S3_ACCESS_KEY_ID=.*|BACKUP_S3_ACCESS_KEY_ID=$garage_key|" \
	-e "s|^BACKUP_S3_SECRET_ACCESS_KEY=.*|BACKUP_S3_SECRET_ACCESS_KEY=$garage_secret|" \
	-e 's|=<.*>$|=test-only-0123456789abcdef0123456789abcdef|' \
	"$root/deploy/.env.example" >"$dir/.env"
if grep -n '<' "$dir/.env" | grep -v '^[0-9]*:#' | grep -v '^[0-9]*:MAIL_FROM='; then
	echo "test-hosted: a placeholder is left in .env" >&2
	exit 1
fi

# As environment, so restore.sh's own `docker compose` finds this stack too.
export COMPOSE_PROJECT_NAME=rakin-hosted-test COMPOSE_FILE="$dir/docker-compose.yml:$dir/garage.yml"
compose() { docker compose "$@"; }
cleanup() {
	status=$?
	[ $status = 0 ] || compose logs --no-color --tail 50 || true
	compose --profile migrate --profile garage-init down -v --remove-orphans >/dev/null 2>&1 || true
	rm -rf "$dir"
	exit $status
}
trap cleanup EXIT

compose run --rm garage-init
compose run --rm migrate
compose up -d --wait --wait-timeout 180
"$root/deploy/smoke.sh" http://localhost

# Backup and restore: a gym's rows go into a backup, and come back out of it.
compose run --rm api python -m app.gyms create --slug meta --name Meta \
	--owner-email owner@example.com --owner-name Owner --owner-phone "+56 9 1234 5678"
compose run --rm backup python -m app.backup run
compose run --rm backup python -m app.backup status
out=$(cd "$dir" && "$root/deploy/restore.sh" latest <<<"$identity")
echo "$out"
grep -q '^ok   - public.gym: 1 rows$' <<<"$out"
grep -q 'every count matches$' <<<"$out"
echo "ok   - a backup restores into a scratch database, every row accounted for"
