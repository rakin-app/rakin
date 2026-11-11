# Deploying Rakin: staging.rakin.app

The hosted instance is one VPS running Docker Compose ([design](technical.md#infrastructure-and-operations)). Staging becomes production for the pilot, so everything here is written for a box that holds real gyms' ledgers.

What lives where:

| Piece | Where |
| --- | --- |
| Images | `ghcr.io/rakin-app/rakin-api` (api, jobs, migrate) and `ghcr.io/rakin-app/rakin-web` (Caddy plus the built SPA), built by [`images.yml`](../.github/workflows/images.yml) for every commit on `main`, tagged `sha-<commit>` and `main` |
| Releases | a `v*` git tag; [`deploy.yml`](../.github/workflows/deploy.yml) tags that commit's images with it and runs it on the host |
| The stack | [`deploy/docker-compose.yml`](../deploy/docker-compose.yml): `caddy`, `api`, `jobs`, `postgres`, the one-shot `migrate`, and `backup` when enabled. No Garage, no Vite, no source mounts |
| Settings | `/srv/rakin/.env` on the host only, from [`deploy/.env.example`](../deploy/.env.example). Never in the repo, the image or a CI secret |
| Deploy and rollback | [`deploy/deploy.sh`](../deploy/deploy.sh), on the host beside the Compose file |
| Post-deploy check | [`deploy/smoke.sh`](../deploy/smoke.sh) `<url>` |
| Backups | the opt-in `backup` service ([`app/backup.py`](../backend/app/backup.py)), nightly to a bucket of their own; [`deploy/restore.sh`](../deploy/restore.sh) restores one into a scratch database ([below](#backups)) |

CI boots this exact stack from each PR's images (`deploy/test-hosted.sh`), smoke-tests it, and backs it up and restores the backup, so a release is never the first time the images, the Caddyfile and the Compose file meet.

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
2. copies that tag's `docker-compose.yml`, `deploy.sh`, `smoke.sh` and `restore.sh` to `/srv/rakin`;
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

Logs rotate at 5 × 20 MB per container.

## Backups

The `backup` service takes one every night at 03:00 in `JOBS_TIMEZONE` ([`app/backup.py`](../backend/app/backup.py)): `pg_dump --format=custom` as the Postgres superuser, piped straight into [age](https://age-encryption.org) to a public key, uploaded to a bucket of its own as `rakin/<BACKUP_ENV>/<UTC timestamp>.dump.age`. The plain dump never touches the disk, and the host holds only the public key: it can write backups but not read them. It also takes one at once when it starts and the last success is over a day old, so a new host has one within minutes.

**Retention:** after each upload it deletes what is not the newest dump of one of the 14 most recent days that have one, or of one of the 8 most recent Sundays (UTC dates). It counts dumps rather than days since today, so a job that stops working never ages the last good backups away. Anything in the bucket not named like a backup is left alone.

**Failure:** a failed backup is logged at `ERROR`, which reaches Sentry like the api's errors. The service then tries again every hour until one succeeds, instead of waiting for the next night. A failure to apply retention after a successful upload is a warning only, in the log and in Sentry: the new backup is safely in the bucket, and the next run prunes again. Each success writes its time and key to `last_success` in the `backup_state` volume:

```sh
docker compose exec backup python -m app.backup status   # the last success; exits 1 if over 26 hours ago
docker compose exec backup python -m app.backup list     # what is in the bucket, newest first
docker compose exec backup python -m app.backup run      # one more backup now
docker compose logs backup                               # "backup uploaded" lines, and any failure
```

### Setting them up

1. **The bucket.** In R2, a second bucket (`rakin-backups`), separate from the proofs' one. Then an API token with **Object Read & Write** on that bucket alone: its key id and secret go in `BACKUP_S3_ACCESS_KEY_ID` and `BACKUP_S3_SECRET_ACCESS_KEY`, the account's endpoint in `BACKUP_S3_ENDPOINT_URL`. The app's token never reaches it, and this one reaches nothing else.
2. **The key, on a laptop, never on the host:**

   ```sh
   age-keygen -o rakin-backup.key        # prints "Public key: age1..."
   ```

   Store the whole file in the team's password manager, then delete it from the laptop. The `age1...` public key goes in `BACKUP_AGE_RECIPIENT`. Losing the private key loses every backup; anyone who has it can read them all.
3. **`.env`:** the `BACKUP_*` lines from [`deploy/.env.example`](../deploy/.env.example), `BACKUP_ENV` being `staging` or `production`, and uncomment `COMPOSE_PROFILES=backup` to turn the service on.
4. Run `docker compose up -d --wait` (or the next deploy, which runs the same), and `docker compose logs backup` shows the first `backup uploaded`; then rehearse a restore, below.

**Backups are opt-in.** The `backup` service sits behind the Compose profile `backup`, so a host whose `.env` has no `COMPOSE_PROFILES=backup` runs and deploys everything else without it, `BACKUP_*` unset. Turned on with a `BACKUP_*` setting missing or invalid, the service does not back up: it logs `backups are enabled but not configured`, naming each variable (never its value), at `ERROR`, so Sentry reports it, and again every day until it is fixed. It stays running rather than exit, so the deploy and the other services go on as normal.

### Restoring, to check a backup

[`deploy/restore.sh`](../deploy/restore.sh) restores a backup into a **scratch** Postgres container and checks it; it never touches the live database. Run it in `/srv/rakin` with the private key on stdin, ideally straight from the password manager over SSH, so the key never lands on the host's disk:

```sh
ssh deploy@<host> 'cd /srv/rakin && ./restore.sh latest' <rakin-backup.key
ssh deploy@<host> 'cd /srv/rakin && ./restore.sh rakin/production/20261110T060000Z.dump.age' <rakin-backup.key
```

It downloads and decrypts the backup in the `backup` service's image, into a Docker volume; restores it with `pg_restore --exit-on-error` into a throwaway `postgres` container with no network (the roles the schema names are created first, without logins); then compares every table's row count with the rows the dump holds, one `ok` or `FAIL` line per table, and exits non-zero on any difference. **The decrypted dump does land on the host's disk while it runs:** in a Docker volume named `rakin-restore-<pid>` (under `/var/lib/docker/volumes/`), readable by root and by anyone in the `docker` group, along with the scratch database restored from it. A `trap` on exit removes the container and the volume, the decrypted dump with them, whether the restore succeeds, fails or is interrupted (they are deleted, not shredded). Only `kill -9` or a crash of the host skips the trap; then `docker rm -f -v rakin-restore-<pid>` and `docker volume rm rakin-restore-<pid>` clean up, and `docker volume ls | grep rakin-restore` shows whether anything was left. So "the host cannot read its backups" holds between rehearsals, not during one. The key itself is never written: it goes from stdin straight into `age`.

Rehearse it before the second gym onboards and quarterly after, as the [design](technical.md#infrastructure-and-operations) says.

### Restoring to live

A deliberate step, by hand, never by `restore.sh`. It replaces the database with the backup: everything since the backup is lost. Check the backup with `restore.sh` first.

On the host, stop everything that writes:

```sh
cd /srv/rakin && docker compose stop caddy api jobs backup
install -d -m 700 ~/restore   # the decrypted dump: only you can read it, and it goes at the end
```

From your laptop, decrypt the backup into it, the key over SSH as for `restore.sh`:

```sh
ssh deploy@<host> 'cd /srv/rakin && docker compose run --rm -T -v ~/restore:/restore backup sh -c \
  "python -m app.backup fetch rakin/production/20261110T060000Z.dump.age /restore/b.age && age -d -i - -o /restore/b.dump /restore/b.age"' \
  <rakin-backup.key
```

Then on the host, replace the database with it:

```sh
cd /srv/rakin
docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose --profile migrate run --rm migrate python -m app.db_bootstrap   # the roles and the owner, as on a new host
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error' <~/restore/b.dump
rm -rf ~/restore
docker compose up -d --wait
./smoke.sh https://<host>
```

The dump carries the schema at its release's migration. If the running release is newer, run `docker compose --profile migrate run --rm migrate` before `up`. The restored database needs the same `FIELD_ENCRYPTION_KEY` it was written under, or the sensitive custom fields stay unreadable. The key only passes through the host's memory; the decrypted dump in `~/restore` does land on its disk, which is why it goes as soon as the restore is done.

Point-in-time recovery (WAL archiving) is not set up; a nightly dump loses up to a day. See the [design](technical.md#infrastructure-and-operations).
