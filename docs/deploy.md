# Deploying Rakin

Hosted Rakin is two VPSs, each running the same Docker Compose stack ([design](technical.md#infrastructure-and-operations)) from the same images:

| Host | Where | Names | Holds |
| --- | --- | --- | --- |
| **Production** | Hetzner, Ashburn, Virginia (US East) | `rakin.app` (the landing page), `app.rakin.app` (the base host: sign-in, `/plataforma`), `<slug>.rakin.app` (each gym); the old `staging.rakin.app` names redirect to these ([Old addresses](#old-addresses)) | the gyms' data |
| **Staging** | Hetzner, Nuremberg, Germany | `sitio.staging.rakin.app` (the next landing page), `staging.rakin.app` (its base host), `<slug>.staging.rakin.app` (the seed's gym) | seed data only, never a gym's ([The staging host](#the-staging-host)) |

A tag deploys to staging first, and to production only once staging passed and the owner approved it ([§5](#5-release)). Everything written here for "the host" holds for both, unless it names one.

Until the switch (#464, [run sheet](#the-switch-464)) the Ashburn host still answers on the staging names, with `BASE_DOMAIN=staging.rakin.app`; the settings that make it production are harmless there until then.

What lives where:

| Piece | Where |
| --- | --- |
| Images | `ghcr.io/rakin-app/rakin-api` (api, jobs, migrate) and `ghcr.io/rakin-app/rakin-web` (Caddy plus the built SPA), built by [`images.yml`](../.github/workflows/images.yml) for every commit on `main`, tagged `sha-<commit>` and `main` |
| Releases | a `v*` git tag; [`deploy.yml`](../.github/workflows/deploy.yml) tags that commit's images with it, runs it on staging, and on production once the owner approves |
| The stack | [`deploy/docker-compose.yml`](../deploy/docker-compose.yml): `caddy`, `api`, `jobs`, `postgres`, the one-shot `migrate`, and `backup` when enabled. No Garage, no Vite, no source mounts |
| Settings | `/srv/rakin/.env` on the host only, from [`deploy/.env.example`](../deploy/.env.example). Never in the repo, the image or a CI secret |
| Deploy and rollback | [`deploy/deploy.sh`](../deploy/deploy.sh), on the host beside the Compose file |
| Post-deploy check | [`deploy/verify.sh`](../deploy/verify.sh) on the host (images, schema, error log), then [`deploy/smoke.sh`](../deploy/smoke.sh) `<url>` |
| Backups | the opt-in `backup` service ([`app/backup.py`](../backend/app/backup.py)), nightly to a bucket of their own; [`deploy/restore.sh`](../deploy/restore.sh) restores one into a scratch database ([below](#backups)) |

CI boots this exact stack from each PR's images (`deploy/test-hosted.sh`), smoke-tests it, and backs it up and restores the backup, so a release is never the first time the images, the Caddyfile and the Compose file meet.

## 1. Provision the VPS

Both hosts are provisioned the same way: Ubuntu 24.04 LTS, 2 vCPU / 4 GB.

- **Production** runs on Hetzner in Ashburn, Virginia (US East), the location the DPA's Anexo A and the privacy notices name (#430). It holds the gyms' data, so a production host elsewhere changes those texts first. In the Hetzner console the owner turns on **delete protection and rebuild protection** for the server and for its primary IPs, so neither the server nor the addresses the DNS points at can go by a slip.
- **Staging** runs on Hetzner in Nuremberg, Germany, a smaller CX-class server. It holds seed data only, never a gym's or a member's, so its location is in no legal text ([below](#the-staging-host)) and its latency does not matter. Protection is optional there.

As root, once on each:

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
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh   # pii-ok: the server's deploy user
# paste the deploy key's public half into /home/deploy/.ssh/authorized_keys (mode 600, owner deploy; pii-ok: on the server)
install -d -m 750 -o deploy -g deploy /srv/rakin

# No password logins, no root over SSH.
printf 'PasswordAuthentication no\nPermitRootLogin no\n' >/etc/ssh/sshd_config.d/10-rakin.conf
systemctl reload ssh
```

Docker publishes ports by writing its own iptables rules, ahead of ufw's. That is harmless here because the Compose file publishes only 80 and 443; never publish Postgres or the api on this host.

Each host has its own deploy key, never shared. Generate it on your machine, not the host: `ssh-keygen -t ed25519 -f rakin-deploy-<staging|production> -C rakin-deploy-<staging|production> -N ""`. Record each host key for CI with `ssh-keyscan -H <host>` (compare its fingerprint with the provider's console first).

## 2. DNS, mail and storage

- **DNS** (Cloudflare): every record **DNS only** (grey cloud), so Caddy terminates TLS and gets its certificates from Let's Encrypt over port 80. Each is an `A` and an `AAAA` record:

  | Name | Points at | For |
  | --- | --- | --- |
  | `rakin.app` (apex), `www` | production | the landing page ([below](#the-landing-page-rakinapp)) |
  | `app` | production | production's base host |
  | `*` | production | production's gyms, `<slug>.rakin.app` ([below](#creating-a-gym)) |
  | `meta.staging` | production | each gym that existed before the switch keeps its old name on production ([Old addresses](#old-addresses)); today only Meta |
  | `staging` | staging | staging's base host |
  | `*.staging` | staging | staging's gyms, and `sitio.staging`, its landing page |
  | `www.sitio.staging` | staging | the `www.` of staging's landing, which redirects to it |

  A wildcard never answers for a name that has records of its own, so `app`, `www`, `staging`, Resend's `send`, `rsend` and `resend._domainkey`, `_dmarc` and Email Routing's MX all keep theirs, and `meta.staging` beats `*.staging`. That is also why each name with records is a reserved slug ([`app/hosts.py`](../backend/app/hosts.py)): a gym by that name would never resolve. Caddy gets every certificate itself.
- **Resend**: add and verify `rakin.app` (its DKIM, SPF and return-path records in Cloudflare, DNS only), then create an API key with sending access for that domain, **one per host**, named for it. It goes in `SMTP_PASSWORD`; `SMTP_HOST=smtp.resend.com`, `SMTP_USERNAME=resend`, and port 587 with `SMTP_SECURITY=starttls`, as `deploy/.env.example` has them. There is no sandbox to leave: a verified domain sends to anyone, which is why staging sends only to `MAIL_ALLOW` ([below](#the-staging-host)). Then, for production only, add a webhook (Webhooks → Add endpoint) to `https://app.rakin.app/api/webhooks/resend` with the `email.bounced` and `email.complained` events, and put its signing secret (`whsec_…`) in `RESEND_WEBHOOK_SECRET`: a hard bounce or a spam complaint then stops all mail to that address, and the ficha says why. Without it the endpoint is a 404 and bounced addresses go on being mailed. The URL must be the base host itself: Resend does not follow a redirect.
- **Object storage**: a bucket in R2 (or S3) per host, with object versioning on where the provider offers it. Production's is named `rakin-staging`, for the days when its host was called staging, and holds the gyms' proofs; renaming it would buy nothing and put those files at risk, so it keeps the name. Staging's is `rakin-staging-seed`. For each, create a key scoped to that bucket alone with object read and write for the api (`S3_*` in `.env`), and separately an admin token for the one-off CORS step below.
- **Sentry**: an organisation on the **US region** (chosen at sign-up and fixed after; its DSNs end in `ingest.us.sentry.io`), as the DPA's annex and the privacy notices say (#430). The EU region was considered for #373 and not kept: the database and the email provider are in the United States already, and an event carries no personal data (#373), so moving Sentry to Germany would not keep anything out of the United States. A project for the api; its DSN goes in `SENTRY_DSN`, the same on both hosts. The api and the jobs both report there. Both hosts run `ENVIRONMENT=production`, so staging sets `SENTRY_ENVIRONMENT=staging` and its events say so; production leaves it empty and reports `production`. What an event leaves out is in `backend/app/sentry.py`.

## 3. The host's `.env`

As `deploy`, copy [`deploy/.env.example`](../deploy/.env.example) to `/srv/rakin/.env`, `chmod 600` it, and fill in every `<...>`: `openssl rand -hex 32` for each password, `SECRET_KEY` and `FIELD_ENCRYPTION_KEY`. Each host gets its own, generated afresh: no secret is ever copied from one host to the other. Keep a copy of each in the team's password manager; the host is the only other place it exists.

The example holds **production's** values. Staging's differ in the names, the mail allow list and `SEED_ONLY`, as [The staging host](#the-staging-host) lists. The settings that tell the two apart:

| Setting | Production | Staging |
| --- | --- | --- |
| `SITE_ADDRESS`, `PUBLIC_BASE_URL` | `app.rakin.app`, `https://app.rakin.app` | `staging.rakin.app`, `https://staging.rakin.app` |
| `BASE_DOMAIN` | `rakin.app` | `staging.rakin.app` |
| `LANDING_HOST` | `rakin.app` | `sitio.staging.rakin.app` |
| `MOVED_FROM_DOMAIN` | `staging.rakin.app`: its names redirect to `BASE_DOMAIN`'s ([Old addresses](#old-addresses)) | empty |
| `SENTRY_ENVIRONMENT` | empty (reports `production`) | `staging` |
| `MAIL_ALLOW` | empty: mail goes to everyone | the team's own addresses; every other recipient is logged, not sent |
| `SEED_ONLY` | unset or `false`: `app.seed` refuses | `1`: `app.seed` and the nightly reset run |
| `STAGING_OPERATORS` | unset | who the nightly reset makes an operator again |
| `COMPOSE_PROFILES`, `BACKUP_*` | `backup`, set ([Backups](#backups)) | unset |

`SECRET_KEY` signs sign-in and unsubscribe links and can be rotated after a leak. That does not sign anyone out, and it breaks the unsubscribe links in emails already sent ([incident response](incident-response.md#5-rotating-secrets)). `FIELD_ENCRYPTION_KEY` encrypts sensitive custom fields: a backup restored under another key has those values unreadable, so never change it without re-encrypting them. `RAKIN_TAG` can stay a placeholder: `deploy.sh` writes it.

## 4. GitHub

Two **environments** (Settings → Environments), each with its own host's secrets and nothing at repository level. An environment missing a secret would fall back to a repository secret of the same name, so a staging deploy could reach production's host: keep none there.

- `staging`: no reviewers.
- `production`: **required reviewer: the owner**, "prevent self-review" off, deployment branches and tags limited to tags `v*` and the branch `main`. A tag push runs on the tag; a run by hand (a rollback) runs on `main`, so without `main` the environment would refuse every rollback.

Secrets, the same names in each:

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | that environment's VPS address |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | the private half of that host's own deploy key |
| `DEPLOY_KNOWN_HOSTS` | that host's `ssh-keyscan -H` output. Required: no host key is trusted unpinned |

While any of the first three is unset in an environment, its job skips the deploy and passes (a fork stays green); with those set and `DEPLOY_KNOWN_HOSTS` unset, the job fails.

Variables, per environment too: `DEPLOY_URL` (`https://staging.rakin.app`, `https://app.rakin.app`; the workflow passes these as defaults) and, optionally, `DEPLOY_DIR` (default `/srv/rakin`).

Every deploy first checks it reached the right host: staging's `.env` has `SEED_ONLY=1` and production's does not (`verify.sh --check-host`). A host without that line is taken for production, so the staging job refuses it before copying or running anything.

The images are pulled with the workflow's own token, logged in for the deploy and out again. To pull by hand on the host (a rollback with no CI), either make the two packages public (Packages → package settings → visibility; the code is public anyway), or `docker login ghcr.io` with a token that has only `read:packages`.

**Rulesets** (Settings → Rules), so that a release can only come one way:

- **Tags `refs/tags/v*`**: only admins create them, and nobody updates or deletes one. A tag is a release, and what a tag names never changes.
- **`main`**: a pull request before merging (no approvals required: the owner cannot approve their own PRs, and the review agent comments rather than approves), and the checks `backend`, `frontend`, `dco` and the hosted-stack job green.

## 5. Release

Releases are signed tags on a commit of `main` whose `ci` and `images` runs passed, and there is one way to make one: [`scripts/release.sh`](../scripts/release.sh) `vX.Y.Z`, as [`RELEASING.md`](../RELEASING.md) explains in plain words for the owner and the PM. It checks the commit, tags it, pushes the tag and follows the run; it never reaches a host itself. Never tag by hand, and never tag a commit that is not on `main`.

`deploy.yml` then:

1. **release**: tags `rakin-api:sha-<commit>` and `rakin-web:sha-<commit>` as `v0.1.0` (no rebuild: what ran in CI is what ships), waiting for `images.yml` if the tag beat it;
2. **staging**: deploys it to the staging host ([`deploy-host.yml`](../.github/workflows/deploy-host.yml), below);
3. **changes**: writes the run's job summary, the page the owner approves from: the tag's notes, production's **last successful deploy** (the newest `production` deployment whose job ran `deploy.sh` and passed every check; a job that skipped for unset secrets deployed nothing and does not count), the commits between the two and the migrations among them, flagged when there are any. If a newer production deploy reached the host and then failed, the summary warns that its tag may be what production runs, since a failed check leaves the new release live: check `releases.log` on the host before approving;
4. **production**: waits for the owner's approval, then backs up (`docker compose exec -T backup python -m app.backup run`, and stops unless it reports `backup uploaded`) and deploys to the production host the same way.

The backup runs against the `backup` service **already running** on the host, under its current Compose file: the new one is copied after it. So production's `.env` needs `COMPOSE_PROFILES=backup` and the service up before its first deploy through this workflow (the production host has it today). Without it the job stops at the backup, before anything is deployed.

Production is only offered once staging passed for that tag. On each host, `deploy-host.yml`:

1. checks the host is the environment's (`SEED_ONLY`, [above](#4-github));
2. copies that tag's `docker-compose.yml`, `deploy.sh`, `smoke.sh`, `restore.sh`, `verify.sh` and `reset-staging.sh` to `/srv/rakin`;
3. runs `./deploy.sh v0.1.0` there: `docker compose pull`, then `docker compose run --rm migrate` (`python -m app.db_bootstrap && alembic upgrade head`), and only once that succeeds `docker compose up -d --wait`. A failed migration leaves the running release untouched;
4. runs `./verify.sh <environment> v0.1.0` there ([`deploy/verify.sh`](../deploy/verify.sh)): caddy, api and jobs run, every rakin-app image is `:v0.1.0`, `alembic current` is the image's `alembic heads`, and the api and jobs logged no `ERROR` in the last 5 minutes (it prints how many and from which loggers, never the lines: read those on the host);
5. runs `deploy/smoke.sh <DEPLOY_URL>`. On a first deploy Caddy may still be waiting for its Let's Encrypt certificate, so while `/healthz` fails to connect, handshake or answer in time, the smoke test waits up to 90 s (`SMOKE_TLS_WAIT`) before checking. An HTTP failure such as a 503 is never waited for.

If a check fails after the deploy, the job's summary prints the rollback line for that host (`./deploy.sh --rollback <previous tag>`, from `releases.log`). After a failed **rollback** to a tag, that line names the release the rollback started from (the one before it in `releases.log`), so it goes forward again, restart only.

`deploy.sh` records the live tag as `RAKIN_TAG` in `.env`, so `docker compose ps`, `logs`, `exec` and so on in `/srv/rakin` target the live release, and appends each run to `/srv/rakin/releases.log`.

### First deploy only: the bucket's CORS rule

The browser PUTs proofs straight to the bucket, another origin than the app's, so the bucket must answer its preflight. After the first deploy on each host, on that host, with the **admin** token for this one run:

```sh
cd /srv/rakin
read -r S3_ACCESS_KEY_ID && read -rs S3_SECRET_ACCESS_KEY && export S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY
# `-e NAME` with no value passes the shell's, keeping the token out of history.
docker compose run --rm -e S3_ACCESS_KEY_ID -e S3_SECRET_ACCESS_KEY api python -m app.blob_cors          # dry run
docker compose run --rm -e S3_ACCESS_KEY_ID -e S3_SECRET_ACCESS_KEY api python -m app.blob_cors --apply  # set it
unset S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY
docker compose run --rm api python -m app.blob_cors --check   # the browser's preflight, PUT and GET
```

The rule allows `PUT` and `GET` with a `Content-Type` header from `PUBLIC_BASE_URL`'s origin, and from every gym's host as `https://*.<BASE_DOMAIN>` ([`app/blob_cors.py`](../backend/app/blob_cors.py)). Re-run `--apply` if `PUBLIC_BASE_URL` or `BASE_DOMAIN` changes; a bucket set before `BASE_DOMAIN` existed needs it once, or proofs cannot be uploaded from a gym's host. Then the browser check: sign in on a gym's host as a student with an owed period (on staging, the seed's), upload a transfer proof from a phone, and see it in the admin's Validar comprobante queue. A CORS failure shows in the browser console as a blocked `PUT` to the bucket's host.

### The landing page: rakin.app

`rakin.app` is a static page about Rakin (#343), served by production; staging serves the next release's at `sitio.staging.rakin.app`, with Rakin's privacy notice at `/privacidad/`. Its source is [`site/`](../site/): `index.html` and `styles.css`, the screenshots in `site/img/`, and [`site/build.py`](../site/build.py), which inlines the styles and the logo, renders [`docs/legal/aviso-de-privacidad-rakin.md`](legal/aviso-de-privacidad-rakin.md) and copies the fonts and icons. The `rakin-web` image runs it in a stage of its own and Caddy serves the result from `/srv/site` on `LANDING_HOST` (default `rakin.app`), with `www.` redirecting to it. So it ships with every release, and a change to the notice reaches the page on the next one.

To see it locally: `cd frontend && npm install` (the fonts), then `uv run site/build.py` and open `site/dist/` with any static server, e.g. `python3 -m http.server -d site/dist`.

The screenshots come only from seed data. [`site/screenshots.py`](../site/screenshots.py) signs in to this checkout's local stack as the seed's people, refuses any host but localhost, and writes each shot at 390×844 (2×) or 1280×800. Take them again after a UX pass:

```sh
docker compose up -d --wait && make seed
uv run --with playwright==1.65.2 playwright install chromium   # once
uv run site/screenshots.py            # or --only hoy-390, repeatable
```

The hero's two screens, `hoy-390` and `hoy-1280`, are the page's LCP image (#461): the script also writes them at in-between widths and in AVIF, and the page preloads them. `uv run site/screenshots.py --hero` writes those again from the 2× captures on disk, with no stack. The loops' posters are set by the page's script once the page has loaded, so they never share the line with the hero.

The contact address is `CONTACT_EMAIL` in `site/build.py`.

### Uptime

Point an external monitor (UptimeRobot, Better Stack, or Cloudflare's health checks) at `https://app.rakin.app/healthz` every 5 minutes, alerting on anything but a 200. It answers 503 when the api cannot reach Postgres. A second, lower-priority one watches `https://staging.rakin.app/healthz`; staging is down for a few seconds every night at its reset.

## 6. Rollback

Any earlier tag, restart only:

```sh
cd /srv/rakin && ./deploy.sh --rollback v0.0.9
```

or, from GitHub, run the **deploy** workflow by hand with that tag, **rollback** ticked and **target** `staging`, `production` or `both`. A production rollback skips staging, still waits for the owner's approval, and takes no backup (nothing migrates). `target: production` without **rollback** is refused: a forward deploy always goes through staging. After the restart `verify.sh --rollback` checks the images and the logs, not `alembic current`: the schema stays the newer one. A rollback never migrates: migrations are additive within a release, so the previous image runs on the newer schema, while its Alembic would refuse a revision it does not know. Under the hood it is `RAKIN_TAG=v0.0.9 docker compose up -d`, which also works by hand. `releases.log` lists what ran before.

A rollback runs the Compose file currently in `/srv/rakin`. The workflow copies the earlier tag's one first; by hand, if `deploy/docker-compose.yml` changed between the two releases, fetch the older one with `git show v0.0.9:deploy/docker-compose.yml`.

If a release's migration is the problem, roll forward instead: fix it in a new migration and tag again. Never run `alembic downgrade` on this host.

## Creating a gym

Each gym is served on its own host, `<slug>.<BASE_DOMAIN>`: Meta at `meta.rakin.app` on production. Real gyms are created on production only; staging holds the seed's gym alone, and never one named like a production gym, whose old `<slug>.staging.rakin.app` name may still point at production ([Old addresses](#old-addresses)). There is no self-service sign-up yet; an operator makes each gym, from the panel or on the host.

**First, the gym signs the [Términos de encargo](legal/terminos-de-encargo.md)** (#367), together with the [Términos de servicio](legal/terminos-de-servicio.md), before any of its data is loaded. Send the current version (its **Versión** line, also `PROCESSOR_TERMS_VERSION` in [`app/gyms.py`](../backend/app/gyms.py)) with the blanks filled in, including the gym's breach contacts (clause 12), which also go in the password manager ([incident response](incident-response.md)). Keep the signed PDF with the company's records, never in a repo, named `<slug>-terminos-de-encargo-<version>.pdf`.

**From the panel** (#437), signed in as an [operator](#platform-operators): **Gimnasios › Nuevo gimnasio** at `https://<base host>/plataforma/nuevo`. It asks what `create` below takes: the gym's name, its slug (checked as it is typed, with the address it makes), its time zone, a grading preset if any, the owner's email and name (RUT and phone optional), and the date on the signed copy of the terms, whose version it shows. The terms are always required there. Once created, the address works at once and the owner is emailed a link and a code that sign in on it, good for 15 minutes; if they lapse, the owner asks for another at the address. The panel and the command write the gym through the same database function, `gym_create` (migration 0077), so the two make the same gym; the panel's are logged in `platform_event` as `gym_created`, then `owner_link_sent`, or `owner_link_failed` when the mail did not go. A gym whose latest link did not go says **Enlace no enviado** in the list, beside its titular, with **Reenviar enlace**, which sends a fresh one to the titular's address.

**From the host**, giving the version and the date on the signed copy:

```sh
cd /srv/rakin
docker compose run --rm api python -m app.gyms create --slug meta --name "Meta" \
  --timezone America/Santiago \
  --owner-email <owner@example.com> --owner-name "<Owner's name>" --owner-rut "<12.345.678-5>" \
  --grading bjj \
  --processor-terms 2026-11-18 --signed-on <YYYY-MM-DD>
```

`create` refuses to run without `--processor-terms` and `--signed-on`, and refuses a version that is not the current one or a date to come. It records both in `processor_terms`, with the gym. `--no-processor-terms` instead is only for an instance the company does not host, whose operator processes no gym's data for the company.

It creates the gym with the programs Adultos and Niños and the default block kinds and no members, plans or classes, and makes the person with that RUT its owner (found if another gym already has them, created otherwise), with that email on Meta's record of them. Without `--owner-rut` the owner is someone new, keyed by the email in this gym. `--owner-phone` is optional: staff need no phone. Grading is optional: `--grading` starts the gym on a preset (`bjj`, `judo-karate`, `muay-thai`), as Meta, a BJJ academy, is above; without it the gym has no grades and shows no belts until its owner sets them up in Ajustes › Graduación. Run again with the same slug, it changes nothing and says so. The slug is the host: lower-case letters, digits and hyphens, and not a name the app keeps (`www`, `app`, `api`, `staging`, `sitio`, `send`, `rsend`, `admin`, `mail` and others, in [`app/hosts.py`](../backend/app/hosts.py)), which are the names that have DNS records of their own or may one day.

Then the owner opens `https://meta.rakin.app`, which shows Meta's name, and signs in with that email. On a gym's host:

- a sign-in link points back to that host, and signs in to that gym, even for someone in several; someone whose address Meta does not have is told so, and not signed in;
- the gym's emails (welcome, statements, receipts, invites) link to it too;
- the session cookie is that host's alone (`__Host-session`), so each gym's host has its own sign-in.

The base host itself, `https://app.rakin.app`, serves sign-in for anyone in any gym, and the operators' panel.

**Certificates.** Caddy gets each gym host's certificate from Let's Encrypt at its first visit (on-demand TLS, [`deploy/Caddyfile`](../deploy/Caddyfile)), after asking the api's `/internal/tls-allowed?domain=` whether a gym has that host. It says yes only for an existing gym's slug, or a slug a gym had that still redirects to it ([Editing a gym](#editing-a-gym)), so no name anyone invents reaches Let's Encrypt, and there is no wildcard certificate or DNS plugin. That `ask` is the rate limit: Caddy 2.8 dropped on-demand TLS's own `interval` and `burst`. The first visit to a new gym's host waits a few seconds for its certificate.

**A gym that already exists** signs the Términos de encargo the same way: one made before #367, such as Meta, and every gym again when the terms get a new version, as a new subprocessor in their Anexo A does (clause 9). Record each signature:

```sh
docker compose run --rm api python -m app.gyms sign-terms --slug meta \
  --processor-terms 2026-11-18 --signed-on <YYYY-MM-DD>
```

Run again with a version the gym already signed, it changes nothing and says so, keeping the date first recorded. `create` on a slug a gym already has records no terms either, and says to use `sign-terms`.

A wrong `--signed-on` is corrected by hand, with the date on the signed copy:

```sh
docker compose exec -T postgres psql -U rakin rakin -v slug=meta -v v=2026-11-18 -v d=<YYYY-MM-DD> <<'SQL'
UPDATE processor_terms SET signed_on = :'d'
WHERE version = :'v' AND gym_id = (SELECT id FROM gym WHERE slug = :'slug');
SQL
```

To see which gyms have not signed the current version, by slug:

```sh
docker compose exec -T postgres psql -U rakin rakin -v v=2026-11-18 <<'SQL'
SELECT g.slug FROM gym g
WHERE NOT EXISTS (SELECT FROM processor_terms t WHERE t.gym_id = g.id AND t.version = :'v');
SQL
```

On a gym listed there, load nothing more until it signs. In these commands and the ones above, `2026-11-18` is the current version: it moves with `PROCESSOR_TERMS_VERSION` in [`app/gyms.py`](../backend/app/gyms.py) and the terms' **Versión** line. psql fills in `:'v'` only from stdin, not from `-c`, so the SQL goes in a heredoc.

## Editing a gym

From the panel (#438): **Gimnasios**, then the gym's name, at `https://<base host>/plataforma/<gym id>`. Every change is a row of `platform_event`, which names the fields changed and never their values.

- **Nombre y contacto**: the gym's name, which its host shows at once, and its titular's name, phone and email, in that gym's record of them only (a titular of two gyms keeps their other gym's record). The email changes only while the titular has never signed in to the gym, to fix a typo at creation; after their first sign-in it is refused (`titular_handover`), because a new address there hands the account over. The titular is never changed here: that is the handover of #321, once it exists. Logged as `gym_edited`.
- **Términos de encargo**: every signature, and **Registrar firma** for the current version, with the date on the signed copy, as `sign-terms` records it: a version already signed changes nothing and keeps its first date. Logged as `terms_recorded` when it recorded one.
- **Dirección**: a new slug. The operator types it again to confirm, and must have proved who they are in the last 10 minutes, or the panel emails them a code first. The old address then answers every request with a **301** to the same path on the new one (a **308** for a method other than GET or HEAD, so a form sent there keeps its method and body) for **90 days** (`gym_slug_alias`, migration 0078), a page of the app as much as the API: Caddy asks the api's `/internal/host` before it serves a page on a gym's host (#472). That check fails open: while the api is down or slow to answer, as during a deploy, the page is served and the old address does not redirect it. It keeps its certificate meanwhile; no other gym, from the panel or `create`, can take it in that time. Renaming back to the old slug takes it again and ends its redirect. Sessions are per host, so whoever was signed in on the old address signs in again on the new one, and links in emails sent before the change go through the redirect. Logged as `gym_renamed`, with `{from, to}`.

To see which old slugs still redirect, and where:

```sh
docker compose exec -T postgres psql -U rakin rakin <<'SQL'
SELECT a.slug, g.slug AS now, a.until FROM gym_slug_alias a JOIN gym g ON g.id = a.gym_id
WHERE a.until > now() ORDER BY a.until;
SQL
```

## Old addresses

Until the switch (#464) production's host was called staging, and its gyms lived at `<slug>.staging.rakin.app`. Those names keep working on production, so that nothing already sent or bookmarked breaks.

**The redirect.** With `MOVED_FROM_DOMAIN=staging.rakin.app`, production's Caddy ([`deploy/Caddyfile`](../deploy/Caddyfile)) answers `<slug>.staging.rakin.app` with a redirect to `<slug>.rakin.app`, and `staging.rakin.app` itself with one to `app.rakin.app`, path and query kept: **301** for GET and HEAD, **308** for any other method, which keeps the method and the body. It is done in Caddy and not in the api because Caddy serves the SPA's pages itself, without asking the api. Each old name gets its certificate on demand, and the api's `ask` allows only `staging.rakin.app` and `<slug>.staging.rakin.app` for a gym's slug or a live alias's, so no name anyone invents reaches Let's Encrypt. A gym renamed since goes through two hops, the old domain's and then its alias's ([Editing a gym](#editing-a-gym)). With the setting empty, as on staging, nothing redirects.

**The DNS record that keeps it alive.** At the switch `staging` and `*.staging` moved to the staging host, so on their own the old names would reach staging instead of the redirect. Each gym that existed before the switch keeps an explicit record, `<slug>.staging` → production (today only `meta.staging`), which beats the wildcard. `staging.rakin.app` itself does not: it is staging's base host now. So:

- **Links in emails already sent** to a gym's old host work, because they go through the redirect: unsubscribe links (signed by `SECRET_KEY`, unchanged, and a person must always be able to stop a gym's email), statements, receipts and invites, which then ask to sign in on the new host. A sign-in link still unused redeems on the new host, since the redirect keeps its token.
- **Links to the old base host** (`staging.rakin.app/plataforma`, a sign-in asked for there) stopped redirecting once the switch moved its DNS. They were 15-minute links or operators' bookmarks: nothing lasting points there.
- **Sessions do not move.** The session cookie is host-only (`__Host-session`), so everyone signed in again, once, on the new host. Nothing carries a session across, and nothing should.
- **The installed app** on a phone keeps the old origin's icon. Opening it follows the 301 to the new host, outside the installed app's scope, so a browser bar shows. Its users reinstall from `<slug>.rakin.app`.

**When it can go.** Never by a date: while the redirect is used, it stays. Caddy writes no access log for that site, so its use cannot be read off the host as it is: the redirect goes 12 months after the switch, or sooner if a `log` directive added to that block for a month shows nobody using it. Then a ticket removes the `<slug>.staging` records, the redirect block and `MOVED_FROM_DOMAIN`. Until then, staging never creates a gym named like a production one.

## Suspending a gym

From the gym's screen in the panel (#439), section **Suspensión**. Suspending asks for a reason, a confirm, and a session proved in the last 10 minutes, as a rename does; so does resuming. Each is a row of `platform_event`: `gym_suspended` with `{slug, reason}`, or `gym_resumed`. Suspending a suspended gym, or resuming an active one, changes nothing and logs nothing. The list shows **Suspendido** and since when.

What suspension does (migration 0079):

- Every path on the gym's address shows only its name and "Este gimnasio está suspendido por ahora. Si eres parte del equipo, escribe a soporte." The address keeps its certificate, so the notice is served over HTTPS.
- Nobody gets a sign-in link into it, and no session starts there. A session that was live answers 401 from the next request. Someone who is also in an active gym still signs in to that one.
- The nightly jobs leave it out: no statements, no overdue emails, no billing periods, lapses, freezes or classes for it.
- Its join link answers `410 gym_suspended` and stores nothing; check-in, like every staff screen, needs a session, which no longer works there. Only the unsubscribe link stays open, because a person must always be able to stop a gym's email, suspended or not.
- Its data stays, every row and file. The Resend webhook, which belongs to no gym, keeps suppressing bounced addresses; Rakin takes no payment webhook yet.

What resuming does: its people sign in again, and on the next nightly run the `catch_up` job runs `freezes`, `billing_periods` and `lapse` for it on each day it missed, in order, before any other job takes it back. Its ledger then holds what it would have held had it never been suspended: the periods that fell due are billed, a plan that would have lapsed in the suspension lapses on that day and is not billed after it, and a freeze booked into it starts and ends on its own dates. The statements and overdue emails of those days are never sent; from the run date on, they go out as for any gym. Classes are made from the run date on. A payment recorded during the suspension counts on the days before it too, so it can save a plan from lapsing.

**Removing a gym** is offered only for a suspended one, and is not possible yet: the panel's **Eliminar** explains the end of service of the Términos de encargo (clause 14), with the dates a removal started today would keep, and `DELETE /api/platform/gyms/{id}` answers `409 removal_unavailable` (`not_suspended` for an active gym). Nothing is deleted until #377 defines how. The schedule, whose numbers live in [`app/platform/removal.py`](../backend/app/platform/removal.py): 30 days for the gym to ask for a full copy of its data and files (deletion does not start sooner unless it asks for it in writing), its rows and files deleted within 30 days after that, and its backups gone within 60 days after the deletion.

To see which gyms are suspended, and which the jobs still owe days:

```sh
docker compose exec -T postgres psql -U rakin rakin <<'SQL'
SELECT slug, suspended_at, suspended_reason, jobs_owed_since FROM gym
WHERE suspended_at IS NOT NULL OR jobs_owed_since IS NOT NULL ORDER BY slug;
SQL
```

## Platform operators

The panel at `https://<base host>/plataforma` (#436) lists every gym Rakin hosts, for the people who run them, creates new ones ([Creating a gym](#creating-a-gym), #437), edits them ([Editing a gym](#editing-a-gym), #438) and suspends them ([Suspending a gym](#suspending-a-gym), #439). Who may sign in there is granted on the host, never from a screen:

```sh
cd /srv/rakin
docker compose run --rm api python -m app.operators grant --email <operator@example.com> --name "<Their name>"
docker compose run --rm api python -m app.operators list
```

They then open `/plataforma` on the base host (`https://app.rakin.app/plataforma` on production, `https://staging.rakin.app/plataforma` on staging), give that email, and sign in with the link or the code it brings. The session lasts 8 hours from sign-in; after that they sign in again. The panel does not exist on a gym's host. `grant` on someone who already is an operator changes nothing.

To take it away:

```sh
docker compose run --rm api python -m app.operators revoke --email <operator@example.com>
```

`revoke` ends their open sessions at once and says how many. Granted again later, they sign in as before. Every grant, revoke, sign-in, sign-out, gym created and edit is a row of `platform_event`, which nothing can change or delete:

```sh
docker compose exec -T postgres psql -U rakin rakin <<'SQL'
SELECT at, action, operator_id, detail FROM platform_event ORDER BY at DESC LIMIT 20;
SQL
```

## Day to day

```sh
cd /srv/rakin
docker compose ps
docker compose logs -f api            # JSON lines; also `jobs`, `caddy`
docker compose exec postgres psql -U rakin rakin
docker compose run --rm api python -m app.jobs.daily --today 2026-11-09   # re-run a day's jobs
```

Logs rotate at 5 × 20 MB per container.

**Minors with no guardian** (#368). Run once on staging and on production after the release that adds "Falta apoderado", and again after any import from before it:

```sh
docker compose exec -T postgres psql -U rakin rakin < deploy/minors-without-guardian.sql
```

It lists each gym's members under 18 with no guardian, by id, never by name. Nothing is sent to them until the gym adds one, and the gym sees each on Hoy and on the ficha, so ask the gym to add the guardian there.

## The staging host

The Nuremberg host (#464) holds **seed data only**, never a gym's data: the seed's gym, the team's own operator accounts and the team's allowed mail addresses. It is provisioned like §1 and deployed by the `staging` environment of `deploy.yml`.

### Its `.env`

From [`deploy/.env.example`](../deploy/.env.example), with **every secret generated afresh**: none is copied from production. Where it differs:

| Setting | Staging |
| --- | --- |
| `SITE_ADDRESS`, `PUBLIC_BASE_URL` | `staging.rakin.app`, `https://staging.rakin.app` |
| `BASE_DOMAIN` | `staging.rakin.app` (the seed's gym at `academia-sur.staging.rakin.app`) |
| `LANDING_HOST` | `sitio.staging.rakin.app`, a preview of the next landing |
| `MOVED_FROM_DOMAIN` | empty |
| `ENVIRONMENT`, `SENTRY_ENVIRONMENT` | `production` (secure cookies, secret checks), `staging` (so Sentry tells the hosts apart); same `SENTRY_DSN` |
| `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, every `POSTGRES_*_PASSWORD` | its own |
| `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | bucket `rakin-staging-seed`, and a token scoped to it alone. Apply its CORS rule once (`app.blob_cors --apply`, [above](#first-deploy-only-the-buckets-cors-rule)) |
| `SMTP_PASSWORD` | a Resend API key of its own, named for staging |
| `MAIL_ALLOW` | the team's own addresses: any other recipient is logged (`mail (not allowed, not sent)`), never sent. The seed's people have `example.com` addresses, which would bounce |
| `RESEND_WEBHOOK_SECRET` | empty |
| `SEED_ONLY` | `1`: `app.seed` runs, and the nightly reset below does |
| `STAGING_OPERATORS` | the PM's and the owner's addresses, comma-separated: made operators again after each reset |
| `COMPOSE_PROFILES`, `BACKUP_*` | unset: nothing on it is worth a backup |

No production key of any kind: no production S3, SMTP, backup or deploy key.

### Seeding it

After its first deploy, as `deploy` in `/srv/rakin`:

```sh
docker compose run --rm api python -m app.seed
docker compose run --rm api python -m app.operators grant --email <address> --name <name>   # the PM, the owner
./reset-staging.sh --install-cron
```

### The nightly reset

[`deploy/reset-staging.sh`](../deploy/reset-staging.sh), copied to `/srv/rakin` by every deploy, puts the host back to fresh seed data every night at 05:00 America/Santiago: the seed's dates stay current and the day's tests are undone. It stops `api`, `jobs` and `caddy`, drops and recreates the database, runs the `migrate` one-shot (bootstrap and migrations), loads the seed, grants operator to each address in `STAGING_OPERATORS`, starts everything and runs `smoke.sh` on `PUBLIC_BASE_URL`. Staging is down for those few seconds.

It **refuses** unless `.env` has `SEED_ONLY=1`, and refuses if the database holds any gym that is not the seed's (`academia-sur`), so on production, or on a staging that somehow got a real gym, it drops nothing. A database that is missing or has no `gym` table yet (a reset that failed halfway) holds no gym, so the next run goes ahead.

`./reset-staging.sh --install-cron` adds it to the `deploy` user's crontab, once. Cron runs in the host's zone (UTC) and Ubuntu's cron has no `CRON_TZ`, so the line runs it hourly with `--cron`, and the script resets only in the 05:00 hour of Santiago time, which follows Chile's clock changes. Re-running `--install-cron` keeps a single line.

Every run, refusals included, is appended to `/srv/rakin/reset.log`: the cron line discards the script's output, so the log is the only place a refused night shows. A failure says which step it stopped at; read the lines above it, then run `./reset-staging.sh` by hand. **If the seed's dates on staging look stale, read `reset.log` first:** a gym that is not the seed's (someone created one on staging) makes every night refuse, and the log names it. Staging never holds a gym's real data, so once the PM has checked that gym is a test, drop the database by hand (`docker compose exec postgres dropdb -U rakin --force rakin`) and run `./reset-staging.sh`: a missing database holds no gym, so it goes ahead, and so does every night after.

A reset and a deploy never run together: both take `/srv/rakin/deploy.lock` (`flock`), and each waits up to 10 minutes for the other. A deploy that lands at 05:00 waits out the reset, which takes seconds. `verify.sh` takes the same lock, so a reset that starts after `deploy.sh` finishes never runs under its checks: they wait for it and then check the stack the reset left up.

```sh
./reset-staging.sh          # reset now
tail -n 20 reset.log
crontab -l                  # 0 * * * * /srv/rakin/reset-staging.sh --cron ...
```

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
3. **`.env`:** the `BACKUP_*` lines from [`deploy/.env.example`](../deploy/.env.example), and uncomment `COMPOSE_PROFILES=backup` to turn the service on. Production's `BACKUP_ENV` is `staging`, for the days when its host was called that, so its backups are under `rakin/staging/`; moving them would put the backups at risk for a folder name, so it stays. The staging host takes no backups: nothing on it is worth one.
4. Run `docker compose up -d --wait` (or the next deploy, which runs the same), and `docker compose logs backup` shows the first `backup uploaded`; then rehearse a restore, below.

**Backups are opt-in.** The `backup` service sits behind the Compose profile `backup`, so a host whose `.env` has no `COMPOSE_PROFILES=backup` runs and deploys everything else without it, `BACKUP_*` unset. Turned on with a `BACKUP_*` setting missing or invalid, the service does not back up: it logs `backups are enabled but not configured`, naming each variable (never its value), at `ERROR`, so Sentry reports it, and again every day until it is fixed. It stays running rather than exit, so the deploy and the other services go on as normal.

### Restoring, to check a backup

[`deploy/restore.sh`](../deploy/restore.sh) restores a backup into a **scratch** Postgres container and checks it; it never touches the live database. Run it in `/srv/rakin` with the private key on stdin, ideally straight from the password manager over SSH, so the key never lands on the host's disk:

```sh
ssh deploy@<host> 'cd /srv/rakin && ./restore.sh latest' <rakin-backup.key
ssh deploy@<host> 'cd /srv/rakin && ./restore.sh rakin/staging/20261110T060000Z.dump.age' <rakin-backup.key
```

It downloads and decrypts the backup in the `backup` service's image, into a Docker volume; restores it with `pg_restore --exit-on-error` into a throwaway `postgres` container with no network (the roles the schema names are created first, without logins); then compares every table's row count with the rows the dump holds, one `ok` or `FAIL` line per table, and exits non-zero on any difference. **The decrypted dump does land on the host's disk while it runs:** in a Docker volume named `rakin-restore-<pid>` (under `/var/lib/docker/volumes/`), readable by root and by anyone in the `docker` group, along with the scratch database restored from it. A `trap` on exit removes the container and the volume, the decrypted dump with them, whether the restore succeeds, fails or is interrupted (they are deleted, not shredded). Only `kill -9` or a crash of the host skips the trap; then `docker rm -f -v rakin-restore-<pid>` and `docker volume rm rakin-restore-<pid>` clean up, and `docker volume ls | grep rakin-restore` shows whether anything was left. So "the host cannot read its backups" holds between rehearsals, not during one. The key itself is never written: it goes from stdin straight into `age`.

Rehearse it before the second gym onboards and quarterly after, as the [design](technical.md#infrastructure-and-operations) says.

### Restoring to live

A deliberate step, by hand, never by `restore.sh`. It replaces the database with the backup: everything since the backup is lost. Check the backup with `restore.sh` first.

On the host, stop everything that writes:

```sh
cd /srv/rakin && docker compose stop caddy api jobs backup
install -d -m 700 $HOME/restore   # the decrypted dump: only you can read it, and it goes at the end
```

From your laptop, decrypt the backup into it, the key over SSH as for `restore.sh`:

```sh
ssh deploy@<host> 'cd /srv/rakin && docker compose run --rm -T -v $HOME/restore:/restore backup sh -c \
  "python -m app.backup fetch rakin/staging/20261110T060000Z.dump.age /restore/b.age && age -d -i - -o /restore/b.dump /restore/b.age"' \
  <rakin-backup.key
```

Then on the host, replace the database with it:

```sh
cd /srv/rakin
docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose --profile migrate run --rm migrate python -m app.db_bootstrap   # the roles and the owner, as on a new host
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error' <$HOME/restore/b.dump
rm -rf $HOME/restore
docker compose up -d --wait
./smoke.sh https://<host>
```

The dump carries the schema at its release's migration. If the running release is newer, run `docker compose --profile migrate run --rm migrate` before `up`. The restored database needs the same `FIELD_ENCRYPTION_KEY` it was written under, or the sensitive custom fields stay unreadable. The key only passes through the host's memory; the decrypted dump in `$HOME/restore` does land on its disk, which is why it goes as soon as the restore is done.

Point-in-time recovery (WAL archiving) is not set up; a nightly dump loses up to a day. See the [design](technical.md#infrastructure-and-operations).

## The switch (#464)

Run once, by the PM: the Ashburn host, until then called staging, becomes production on the `rakin.app` names, and the Nuremberg host becomes staging. This is the record of how; after it, every release goes through [§5](#5-release).

**The quiet hour:** a weekday, 22:00–23:00 America/Santiago, after Meta's last class and clear of the nightly jobs and the 03:00 backup. The owner confirms the day with Meta's owner.

**What Meta's owner sees:** the old address sends them to `meta.rakin.app`; everyone signs in again, once; the app icon is installed again. No data moves. The owner sends Meta's owner this two days before, adapted as they see fit:

> El [día] entre 22:00 y 23:00 Rakin cambia de dirección: Meta pasa a meta.rakin.app. La dirección antigua seguirá funcionando y llevará a la nueva. Ese día todos (equipo y alumnos) deben volver a entrar con su correo, una sola vez, y quien tenga el ícono instalado en el teléfono debe instalarlo de nuevo desde meta.rakin.app. No se pierde ningún dato.

**Before the day:**

- Every build ticket of #464 merged and released to the current host, where it is harmless (`MOVED_FROM_DOMAIN` unset).
- The staging host deployed through the `staging` environment, seeded, smoke-tested ([The staging host](#the-staging-host)).
- **Step 0, on staging:** release the current `main` with `scripts/release.sh`; roll it back to the previous tag by a dispatch (`target: staging`, **rollback** ticked); `verify.sh` passes on it; release again. Production is not approved in this rehearsal, or only as a rollback restart of its live tag, which is harmless.
- The owner has turned on Hetzner's delete and rebuild protection for production ([§1](#1-provision-the-vps)).
- At least a day earlier, TTL 60 s on `staging`, `*.staging`, the apex and `www` (Cloudflare's Auto is 300 s), so a way back over DNS is quick.

| # | Step | Check | Way back |
| --- | --- | --- | --- |
| 1 | Backup: `docker compose exec -T backup python -m app.backup run`, then `./restore.sh latest` with the key from the password manager. Copy `/srv/rakin/.env` to `.env.pre-464` (mode 600). | `backup uploaded`; every table `ok`. | Nothing changed yet. |
| 2 | Reserved names: every record name under `rakin.app` in Cloudflare is reserved in [`app/hosts.py`](../backend/app/hosts.py) or is a gym; no gym has `sitio`, `send` or `rsend` (`SELECT slug FROM gym WHERE slug IN ('sitio','send','rsend')`). | All accounted for; the query returns nothing. | — |
| 3 | DNS add: `app`, `*` and `meta.staging` → production (A + AAAA). `meta.staging` already resolves there through `*.staging`, so this changes nothing yet. | `dig +short` for `app.rakin.app`, `x.rakin.app` and `meta.staging.rakin.app` gives production's IPs. | Delete the three records. |
| 4 | `.env`: `SITE_ADDRESS=app.rakin.app`, `PUBLIC_BASE_URL=https://app.rakin.app`, `BASE_DOMAIN=rakin.app`, `MOVED_FROM_DOMAIN=staging.rakin.app`; then `docker compose up -d --wait`. | `./smoke.sh https://app.rakin.app` passes (it waits for the new certificate); `curl -sI https://meta.rakin.app` is a 200 once its certificate is issued; `curl -sI 'https://meta.staging.rakin.app/alumnos?x=1'` is a 301 to `https://meta.rakin.app/alumnos?x=1`, and the same with `-X POST` a 308; `curl -sI https://staging.rakin.app/plataforma` is a 301 to `https://app.rakin.app/plataforma`; `https://rakin.app` is still the landing page; `docker compose logs caddy` shows no ACME errors. | `cp .env.pre-464 .env && docker compose up -d --wait`, then `./smoke.sh https://staging.rakin.app`. |
| 5 | Bucket CORS: `app.blob_cors --apply` with the owner's admin token, then `--check` ([§5](#first-deploy-only-the-buckets-cors-rule)). | `--check` passes for `https://app.rakin.app` and `https://meta.rakin.app`. | `--apply` again under the `.env.pre-464` values. |
| 6 | Resend: the webhook's URL → `https://app.rakin.app/api/webhooks/resend`, then send Resend's test event. | A 200 in Resend's log. | Set the URL back. |
| 7 | Browser checks: sign in at `meta.rakin.app` with the owner's own test account; upload a proof at a phone's width; sign in at `app.rakin.app/plataforma` as an operator; an old unsubscribe link from a real email follows the redirect and shows its page. | All work; no CORS error in the console. | Step 4's way back, then 5's and 6's. |
| 8 | GitHub ([§4](#4-github)): create the `production` environment (required reviewer the owner; deployments from tags `v*` and the branch `main`, which a rollback dispatch runs on) and copy the four repository-level `DEPLOY_*` values into it, with `DEPLOY_URL=https://app.rakin.app`. The `staging` environment gets the new host's four values and `DEPLOY_URL=https://staging.rakin.app`. **Delete the repository-level `DEPLOY_*`.** Add the rulesets. Then a dispatch with the current tag, `target: both`, **rollback** ticked. | Staging's job deploys to the new host; production's waits for approval and, approved, restarts and passes its checks on `https://app.rakin.app`. | Re-add the repository-level secrets from the password manager; delete the environments. |
| 9 | DNS move: `staging` and `*.staging` → the staging host (A + AAAA), and add `www.sitio.staging` → the staging host. `meta.staging` stays on production. | `dig` shows the split; `https://staging.rakin.app` is staging's sign-in page, with no Meta; `https://academia-sur.staging.rakin.app` serves the seed's gym; `https://meta.staging.rakin.app` still 301s to `meta.rakin.app`. | Point `staging` and `*.staging` back at production (the 60 s TTL makes it quick). |
| 10 | Uptime monitors moved ([Uptime](#uptime)); after a test error on each host, Sentry shows `production` from production and `staging` from staging. The owner tells Meta's owner it is done. | Monitors green; the two environments apart in Sentry. | — |
| 11 | A day later: TTLs back to Auto; the PM updates its own notes on the servers. | — | — |
