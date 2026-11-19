#!/usr/bin/env bash
# Boot the hosted stack from images built here, the way deploy.sh runs it
# (migrate, then up), and smoke-test it. CI runs this on every PR, so a
# release is never the first time the images, Caddyfile and hosted Compose
# file meet. Needs Docker and port 80; the stack is removed afterwards.
#
# Caddy serves plain HTTP on :80 here (SITE_ADDRESS=:80): no certificate,
# no DNS; the landing page alone is on HTTPS, from Caddy's own CA. Object
# storage and mail (Resend) are configured but never reached.
# Backups are, under COMPOSE_PROFILES=backup: a Garage beside the stack stands in for their R2 bucket, and
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
	-e 's|^LANDING_HOST=.*|LANDING_HOST=landing.localhost|' \
	-e 's|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=http://localhost|' \
	-e 's|^MOVED_FROM_DOMAIN=.*|MOVED_FROM_DOMAIN=moved.localhost|' \
	-e 's|^SENTRY_DSN=.*|SENTRY_DSN=|' \
	-e 's|^RESEND_WEBHOOK_SECRET=.*|RESEND_WEBHOOK_SECRET=whsec_dGVzdC1vbmx5IHNpZ25pbmcgc2VjcmV0|' \
	-e 's|^# COMPOSE_PROFILES=backup$|COMPOSE_PROFILES=backup|' \
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

grep -qx 'COMPOSE_PROFILES=backup' "$dir/.env"

# Backups are opt-in: a host with no BACKUP_* and no profile renders, without them.
grep -v -e '^BACKUP_' -e '^COMPOSE_PROFILES=' "$dir/.env" >"$dir/bare.env"
services=$(docker compose -f "$dir/docker-compose.yml" --env-file "$dir/bare.env" config --services)
if grep -qx backup <<<"$services"; then
	echo "test-hosted: backup runs without COMPOSE_PROFILES=backup" >&2
	exit 1
fi
rm "$dir/bare.env"
echo "ok   - the stack renders without BACKUP_*, and without the backup service"

# As environment, so restore.sh's own `docker compose` finds this stack too.
export COMPOSE_PROJECT_NAME=rakin-hosted-test COMPOSE_FILE="$dir/docker-compose.yml:$dir/garage.yml"
compose() { docker compose "$@"; }
cleanup() {
	status=$?
	[ $status = 0 ] || compose logs --no-color --tail 50 || true
	compose --profile migrate --profile garage-init --profile backup down -v --remove-orphans >/dev/null 2>&1 || true
	rm -rf "$dir"
	exit $status
}
trap cleanup EXIT

compose run --rm garage-init
compose run --rm migrate
compose up -d --wait --wait-timeout 180
"$root/deploy/smoke.sh" http://localhost
# What the deploy workflow runs after deploy.sh, against the real Compose,
# Alembic and logs. It runs from the directory with .env, as on a host.
cp "$root/deploy/verify.sh" "$dir/"
# The hosts and CI have util-linux's flock; a laptop may not, and the lock
# has nothing to guard against here.
command -v flock >/dev/null || export FLOCK=true
"$dir/verify.sh" production "$RAKIN_TAG"
echo "ok   - verify.sh passes the booted stack"

# The landing page (#343), on its own host. A .localhost name gets a certificate
# from Caddy's own CA, so this is HTTPS as in production, with -k.
landing() { # landing <host> <path> [curl options]
	curl -sS -k --max-time 15 --resolve "$1:443:127.0.0.1" "${@:3}" "https://$1$2"
}
# Caddy issues those certificates in the background at start: wait for one.
for _ in $(seq 30); do landing landing.localhost / -o /dev/null 2>/dev/null && break; sleep 1; done
# Into a variable first: `grep -q` stops reading at its match, and under
# pipefail curl's write error (23) would fail the test.
page=$(landing landing.localhost /)
grep -q 'La app para llevar tu academia, gimnasio o club' <<<"$page"
notice=$(landing landing.localhost /privacidad/)
grep -q 'Política de privacidad de Rakin' <<<"$notice"
grep -q 'Versión preliminar, en revisión' <<<"$notice"
# The notice's drafting notes stay in the repo: never on the public page.
if grep -q -E 'ABOGADO|PENDIENTE|BORRADOR' <<<"$notice"; then
	echo "test-hosted: /privacidad/ shows a drafting note" >&2
	exit 1
fi
# A capture and a loop, by the names site/build.py gave them for their content, each
# served as itself and cached for a week.
served() { # served <path> <content type>
	[ "$(landing landing.localhost "$1" -o /dev/null -w '%{http_code} %{content_type}')" = "200 $2" ]
	headers=$(landing landing.localhost "$1" -o /dev/null -D -)
	grep -qi '^cache-control: public, max-age=604800' <<<"$headers"
}
[[ $page =~ /img/[A-Za-z0-9.-]+\.webp ]]
served "${BASH_REMATCH[0]}" image/webp
# The hero's image is AVIF too (#461): Caddy has to name it as such.
[[ $page =~ /img/[A-Za-z0-9.-]+\.avif ]]
served "${BASH_REMATCH[0]}" image/avif
[[ $page =~ /video/[A-Za-z0-9.-]+\.webm ]]
served "${BASH_REMATCH[0]}" video/webm
[ "$(landing www.landing.localhost '/x?y=1' -o /dev/null -w '%{http_code} %{redirect_url}')" = "301 https://landing.localhost/x?y=1" ]
echo "ok   - the landing page, its privacy notice (no drafting notes), a capture and a loop cached for a week, and www redirecting to it"
compose ps --services --status running | grep -qx backup
echo "ok   - with COMPOSE_PROFILES=backup, up starts the backup service"

# Staging's nightly reset (#469), on this stack as on the staging host: seed
# data only, so it drops the database and reseeds it. The seed's proof files go
# to a local store here, since S3 is never reached.
cp "$root/deploy/reset-staging.sh" "$root/deploy/smoke.sh" "$dir/"
sed -i.bak -e 's|^SEED_ONLY=.*|SEED_ONLY=1|' -e 's|^BLOB_STORE=.*|BLOB_STORE=local|' "$dir/.env"
rm "$dir/.env.bak"
echo 'STAGING_OPERATORS=pm@example.com' >>"$dir/.env"
(cd "$dir" && ./reset-staging.sh)
gyms() { compose exec -T postgres psql -U rakin -d rakin -tA -c 'SELECT slug FROM gym ORDER BY slug'; }
[ "$(gyms)" = academia-sur ]
[ "$(compose exec -T postgres psql -U rakin -d rakin -tA -c 'SELECT email FROM platform_operator')" = pm@example.com ]
grep -q 'reset: done: academia-sur reseeded, 1 operator(s) granted' "$dir/reset.log"
echo "ok   - reset-staging.sh drops, migrates and reseeds a seed-only database, and grants its operators"

# Backup and restore: a gym's rows go into a backup, and come back out of it.
compose run --rm api python -m app.gyms create --slug meta --name Meta \
	--owner-email owner@example.com --owner-name Owner --owner-phone "+56 9 1234 5678" \
	--processor-terms 2026-11-18 --signed-on 2026-11-18
# With a gym that is not the seed's, the reset refuses and the gym stays.
if (cd "$dir" && ./reset-staging.sh) >/dev/null 2>&1; then
	echo "test-hosted: reset-staging.sh dropped a database holding meta" >&2
	exit 1
fi
grep -qx meta <<<"$(gyms)"
grep -q "reset: refusing: the database holds gyms that are not the seed's: meta" "$dir/reset.log"
echo "ok   - reset-staging.sh refuses a database holding a gym that is not the seed's"

# The gyms' old domain (#464): its names redirect, path and query kept, 301 for
# GET and HEAD and 308 for the rest. Their certificates are on demand, as in
# production, from Caddy's own CA for a .localhost name.
redirect() { # redirect <host> <path> [curl options]: "<code> <location>"
	landing "$1" "$2" -o /dev/null -w '%{http_code} %{redirect_url}' "${@:3}"
}
for _ in $(seq 30); do landing meta.moved.localhost / -o /dev/null 2>/dev/null && break; sleep 1; done
[ "$(redirect meta.moved.localhost '/alumnos?x=1&y=2')" = "301 https://meta.staging.rakin.app/alumnos?x=1&y=2" ]
[ "$(redirect meta.moved.localhost /alumnos -I)" = "301 https://meta.staging.rakin.app/alumnos" ]
[ "$(redirect meta.moved.localhost '/api/x?y=1' -X POST -d z=1)" = "308 https://meta.staging.rakin.app/api/x?y=1" ]
[ "$(redirect moved.localhost '/plataforma?a=b')" = "301 http://localhost/plataforma?a=b" ]
[ "$(redirect moved.localhost /api/auth -X POST -d z=1)" = "308 http://localhost/api/auth" ]
echo "ok   - the old domain redirects: a gym's host to its new one (301, path and query kept; 308 for POST), the old base host to the base host"

# Caddy's ask: the old domain's names are allowed only for a gym, and for the
# old base host; no certificate, so no handshake, for any other.
ask() { # ask <domain>: the api's status code, from inside the stack
	compose exec -T caddy wget -q -S -O /dev/null "http://api:8000/internal/tls-allowed?domain=$1" 2>&1 |
		sed -n 's/^ *HTTP\/[0-9.]* \([0-9]*\).*/\1/p' | tail -1
}
[ "$(ask meta.moved.localhost)" = 200 ]
[ "$(ask moved.localhost)" = 200 ]
[ "$(ask nadie.moved.localhost)" = 404 ]
if landing nadie.moved.localhost / -o /dev/null 2>/dev/null; then
	echo "test-hosted: a host no gym has under the old domain got a certificate" >&2
	exit 1
fi
echo "ok   - the old domain's ask allows a gym and the old base host, and 404s a slug no gym has (no certificate)"

# The production deploy's backup, as deploy-host.yml runs it: in the running
# service, and it must say "backup uploaded".
out=$(compose exec -T backup python -m app.backup run 2>&1)
grep -q 'backup uploaded' <<<"$out"
compose run --rm backup python -m app.backup status
out=$(cd "$dir" && "$root/deploy/restore.sh" latest <<<"$identity")
echo "$out"
# The seed's gym, from the reset above, and meta.
grep -q '^ok   - public.gym: 2 rows$' <<<"$out"
grep -q 'every count matches$' <<<"$out"
echo "ok   - a backup restores into a scratch database, every row accounted for"

# Enabled with a setting missing: the job names it, exits non-zero, and backs nothing up.
if out=$(compose run --rm -T -e BACKUP_AGE_RECIPIENT= backup python -m app.backup run 2>&1); then
	echo "test-hosted: a backup without BACKUP_AGE_RECIPIENT succeeded" >&2
	exit 1
fi
grep -q 'backups are enabled but not configured.*BACKUP_AGE_RECIPIENT: Field required' <<<"$out"
echo "ok   - enabled without BACKUP_AGE_RECIPIENT, the job says so and refuses"
