# Deploying Rakin: staging.rakin.app

The hosted instance is one VPS running Docker Compose ([design](technical.md#infrastructure-and-operations)). Staging becomes production for the pilot, so everything here is written for a box that holds real gyms' ledgers.

What lives where:

| Piece | Where |
| --- | --- |
| Images | `ghcr.io/rakin-app/rakin-api` (api, jobs, migrate) and `ghcr.io/rakin-app/rakin-web` (Caddy plus the built SPA), built by [`images.yml`](../.github/workflows/images.yml) for every commit on `main`, tagged `sha-<commit>` and `main` |
| Releases | a `v*` git tag; [`deploy.yml`](../.github/workflows/deploy.yml) tags that commit's images with it and runs it on the host |
| The stack | [`deploy/docker-compose.yml`](../deploy/docker-compose.yml): `caddy`, `api`, `jobs`, `postgres`, and the one-shot `migrate`. No Garage, no Vite, no source mounts |
| Settings | `/srv/rakin/.env` on the host only, from [`deploy/.env.example`](../deploy/.env.example). Never in the repo, the image or a CI secret |
| Deploy and rollback | [`deploy/deploy.sh`](../deploy/deploy.sh), on the host beside the Compose file |
| Post-deploy check | [`deploy/smoke.sh`](../deploy/smoke.sh) `<url>` |

CI boots this exact stack from each PR's images (`deploy/test-hosted.sh`) and smoke-tests it, so a release is never the first time the images, the Caddyfile and the Compose file meet.

## 1. Provision the VPS

Ubuntu 24.04 LTS, 2 vCPU / 4 GB, in São Paulo if the provider has it, otherwise US East. As root, once:

```sh
# Docker Engine and the Compose plugin, from Docker's apt repository.
apt-get update && apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  >/etc/apt/sources.list.d/docker.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Security updates install themselves; reboots stay a person's call.
apt-get install -y unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

# Firewall: SSH, HTTP (ACME and the redirect) and HTTPS, nothing else.
ufw default deny incoming && ufw default allow outgoing
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp
ufw --force enable

# The deploy user: SSH key only, may run Docker (which is root-equivalent:
# guard the key accordingly), owns /srv/rakin.
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
# paste the deploy key's public half into /home/deploy/.ssh/authorized_keys (mode 600, owner deploy)
install -d -m 750 -o deploy -g deploy /srv/rakin

# No password logins, no root over SSH.
printf 'PasswordAuthentication no\nPermitRootLogin no\n' >/etc/ssh/sshd_config.d/10-rakin.conf
systemctl reload ssh
```

Docker publishes ports by writing its own iptables rules, ahead of ufw's. That is harmless here because the Compose file publishes only 80 and 443; never publish Postgres or the api on this host.

Generate the deploy key on your machine, not the host: `ssh-keygen -t ed25519 -f rakin-deploy -C rakin-deploy -N ""`. Record the host key for CI with `ssh-keyscan -H <host>` (compare its fingerprint with the provider's console first).

## 2. DNS, mail and storage

- **DNS** (Cloudflare): an `A` (and `AAAA`) record `staging` → the VPS, **DNS only** (grey cloud), so Caddy terminates TLS and gets its certificate from Let's Encrypt over port 80. And for the gyms' own hosts ([below](#creating-a-gym)), a wildcard `A` (and `AAAA`) record `*.staging` → the VPS, DNS only too. Production's will be `rakin.app` and `*.rakin.app`.
- **Resend**: add and verify `rakin.app` (its DKIM, SPF and return-path records in Cloudflare, DNS only), then create an API key with sending access for that domain. It goes in `SMTP_PASSWORD`; `SMTP_HOST=smtp.resend.com`, `SMTP_USERNAME=resend`, and port 587 with `SMTP_SECURITY=starttls`, as `deploy/.env.example` has them. There is no sandbox to leave: a verified domain sends to anyone.
- **Object storage**: a bucket in R2 (or S3), with object versioning on where the provider offers it. Create a key scoped to that bucket with object read and write for the api (`S3_*` in `.env`), and separately an admin token for the one-off CORS step below.
- **Sentry**: a project for the api; its DSN goes in `SENTRY_DSN`. The api and the jobs both report there.

## 3. The host's `.env`

As `deploy`, copy [`deploy/.env.example`](../deploy/.env.example) to `/srv/rakin/.env`, `chmod 600` it, and fill in every `<...>`: `openssl rand -hex 32` for each password, `SECRET_KEY` and `FIELD_ENCRYPTION_KEY`. Keep a copy in the team's password manager; the host is the only other place it exists. `SECRET_KEY` signs links and upload URLs and can be rotated after a leak; that only signs everyone out. `FIELD_ENCRYPTION_KEY` encrypts sensitive custom fields: a backup restored under another key has those values unreadable, so never change it without re-encrypting them. `RAKIN_TAG` can stay a placeholder: `deploy.sh` writes it.

## 4. GitHub

Repository **secrets** (Settings → Secrets and variables → Actions). Repository level, not an environment's: the workflow checks them before it enters the `staging` environment, and skips the deploy (passing) while any of the first three is unset.

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | the VPS's address |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | the private half of the deploy key |
| `DEPLOY_KNOWN_HOSTS` | the `ssh-keyscan -H` output. Optional, but without it the workflow trusts whatever key answers |

Optional repository **variables**: `DEPLOY_URL` (default `https://staging.rakin.app`) and `DEPLOY_DIR` (default `/srv/rakin`).

The images are pulled with the workflow's own token, logged in for the deploy and out again. To pull by hand on the host (a rollback with no CI), either make the two packages public (Packages → package settings → visibility; the code is public anyway), or `docker login ghcr.io` with a token that has only `read:packages`.

## 5. Release

Releases are tags on a commit of `main` whose images exist (`images.yml` has run):

```sh
git tag -s v0.1.0 -m v0.1.0 && git push origin v0.1.0
```

`deploy.yml` then:

1. tags `rakin-api:sha-<commit>` and `rakin-web:sha-<commit>` as `v0.1.0` (no rebuild: what ran in CI is what ships), waiting for `images.yml` if the tag beat it;
2. copies that tag's `docker-compose.yml`, `deploy.sh` and `smoke.sh` to `/srv/rakin`;
3. runs `./deploy.sh v0.1.0` there: `docker compose pull`, then `docker compose run --rm migrate` (`python -m app.db_bootstrap && alembic upgrade head`), and only once that succeeds `docker compose up -d --wait`. A failed migration leaves the running release untouched;
4. runs `deploy/smoke.sh https://staging.rakin.app`.

`deploy.sh` records the live tag as `RAKIN_TAG` in `.env`, so `docker compose ps`, `logs`, `exec` and so on in `/srv/rakin` target the live release, and appends each run to `/srv/rakin/releases.log`.

### First deploy only: the bucket's CORS rule

The browser PUTs proofs straight to the bucket, another origin than the app's, so the bucket must answer its preflight. After the first deploy, on the host, with the **admin** token for this one run:

```sh
cd /srv/rakin
read -r S3_ACCESS_KEY_ID && read -rs S3_SECRET_ACCESS_KEY && export S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY
# `-e NAME` with no value passes the shell's, keeping the token out of history.
docker compose run --rm -e S3_ACCESS_KEY_ID -e S3_SECRET_ACCESS_KEY api python -m app.blob_cors          # dry run
docker compose run --rm -e S3_ACCESS_KEY_ID -e S3_SECRET_ACCESS_KEY api python -m app.blob_cors --apply  # set it
unset S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY
docker compose run --rm api python -m app.blob_cors --check   # the browser's preflight, PUT and GET
```

The rule allows `PUT` and `GET` with a `Content-Type` header from `PUBLIC_BASE_URL`'s origin, and from every gym's host as `https://*.<BASE_DOMAIN>` ([`app/blob_cors.py`](../backend/app/blob_cors.py)). Re-run `--apply` if `PUBLIC_BASE_URL` or `BASE_DOMAIN` changes; a bucket set before `BASE_DOMAIN` existed needs it once, or proofs cannot be uploaded from a gym's host. Then the browser check: sign in on staging as a student with an owed period, upload a transfer proof from a phone, and see it in the admin's Validar comprobante queue. A CORS failure shows in the browser console as a blocked `PUT` to the bucket's host.

### Uptime

Point an external monitor (UptimeRobot, Better Stack, or Cloudflare's health checks) at `https://staging.rakin.app/healthz` every 5 minutes, alerting on anything but a 200. It answers 503 when the api cannot reach Postgres.

## 6. Rollback

Any earlier tag, restart only:

```sh
cd /srv/rakin && ./deploy.sh --rollback v0.0.9
```

or, from GitHub, run the **deploy** workflow by hand with that tag and **rollback** ticked. A rollback never migrates: migrations are additive within a release, so the previous image runs on the newer schema, while its Alembic would refuse a revision it does not know. Under the hood it is `RAKIN_TAG=v0.0.9 docker compose up -d`, which also works by hand. `releases.log` lists what ran before.

A rollback runs the Compose file currently in `/srv/rakin`. The workflow copies the earlier tag's one first; by hand, if `deploy/docker-compose.yml` changed between the two releases, fetch the older one with `git show v0.0.9:deploy/docker-compose.yml`.

If a release's migration is the problem, roll forward instead: fix it in a new migration and tag again. Never run `alembic downgrade` on this host.

## Creating a gym

Each gym is served on its own host, `<slug>.<BASE_DOMAIN>`: Meta at `meta.staging.rakin.app` on staging, `meta.rakin.app` once production's `BASE_DOMAIN` is `rakin.app`. There is no self-service sign-up yet; a gym is made on the host:

```sh
cd /srv/rakin
docker compose run --rm api python -m app.gyms create --slug meta --name "Meta" \
  --timezone America/Santiago \
  --owner-email <owner@example.com> --owner-name "<Owner's name>" --owner-rut "<12.345.678-5>"
```

It creates the gym with what the demo gym has before anyone trains there (the BJJ grading scheme, its programs and the default block kinds) and no members, plans or classes, and makes the person with that RUT its owner (found if another gym already has them, created otherwise), with that email on Meta's record of them. Without `--owner-rut` the owner is someone new, keyed by the email in this gym. `--owner-phone` is optional: staff need no phone. Run again with the same slug, it changes nothing and says so. The slug is the host: lower-case letters, digits and hyphens, and not a name the app keeps (`www`, `app`, `api`, `staging`, `admin`, `mail` and others, in [`app/hosts.py`](../backend/app/hosts.py)).

Then the owner opens `https://meta.staging.rakin.app`, which shows Meta's name, and signs in with that email. On a gym's host:

- a sign-in link points back to that host, and signs in to that gym, even for someone in several; someone whose address Meta does not have is told so, and not signed in;
- the gym's emails (welcome, statements, receipts, invites) link to it too;
- the session cookie is that host's alone (`__Host-session`), so each gym's host has its own sign-in.

`https://staging.rakin.app` itself works as before.

**Certificates.** Caddy gets each gym host's certificate from Let's Encrypt at its first visit (on-demand TLS, [`deploy/Caddyfile`](../deploy/Caddyfile)), after asking the api's `/internal/tls-allowed?domain=` whether a gym has that host. It says yes only for an existing gym's slug, so no name anyone invents reaches Let's Encrypt, and there is no wildcard certificate or DNS plugin. That `ask` is the rate limit: Caddy 2.8 dropped on-demand TLS's own `interval` and `burst`. The first visit to a new gym's host waits a few seconds for its certificate.

## Day to day

```sh
cd /srv/rakin
docker compose ps
docker compose logs -f api            # JSON lines; also `jobs`, `caddy`
docker compose exec postgres psql -U rakin rakin
docker compose run --rm api python -m app.jobs.daily --today 2026-11-09   # re-run a day's jobs
```

Logs rotate at 5 × 20 MB per container. Backups (`pg_dump` to object storage, WAL archiving) are not set up by any of this yet; see the [design](technical.md#infrastructure-and-operations).
