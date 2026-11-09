# Rakin

**[Español](README.es.md)** · English

Rakin (*Mapudungun: to count*) is an open-source, sport-agnostic membership and fee-tracking platform for small martial-arts gyms. It replaces the spreadsheet plus WhatsApp group that most gyms run on.

The core loop: **member → plan → due date → reminder → bank transfer arrives → validated in the ledger → silence.** Rakin never processes money in v1. It tracks, reminds and reconciles transfers the gym already receives.

> **Status:** pre-alpha. The [local stack](#run-locally) runs, but there is no product yet. Follow the [roadmap](https://github.com/orgs/rakin-app/projects) and [milestones](https://github.com/rakin-app/rakin/milestones).

## What it is

- An append-only **ledger** for monthly fees, credit packs, prepaid plans, drop-ins and trials
- **Five-second attendance** for coaches, with a class log
- A thin **student page** reached by magic link: what I owe, when, and how to prove I paid
- Configurable **grading schemes, plans and custom fields** so BJJ, judo, Muay Thai or boxing all fit without sport-specific code

It is not a CRM, a booking system, a payment processor or a native app. It is a PWA. Email is the system of record and WhatsApp is the reminder channel.

## Stack

FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL (row-level security) · Vite SPA + TanStack Query · `vite-plugin-pwa` · Caddy · Docker Compose.

## Docs

- [Product](docs/product.md): personas, principles, scope by release
- [Technical design](docs/technical.md): domain model, state machines, architecture, operations, compliance
- [UI design](docs/design/ui-design.html): mobile admin, coach and student screens plus the desktop ledger (open in a browser)
- [Architecture decisions](docs/adr/): ADRs, starting with the [frontend framework](docs/adr/0001-frontend-framework.md)
- [Frontend](frontend/README.md): running and checking the SPA

## Run locally

You need [Docker](https://docs.docker.com/get-docker/) with Compose v2.24 or newer, and nothing else: Python, Node and Postgres all run in containers.

```sh
git clone https://github.com/rakin-app/rakin.git && cd rakin
cp .env.example .env        # optional: every value has a working local default
docker compose up
```

The first run builds the API image and installs the SPA's packages, a few minutes in all. Caddy only starts once the API and the dev server pass their healthchecks, so the first page load is not a 502; `docker compose up -d --wait` returns at that point. Then:

- http://localhost:8080 serves the SPA, with the API on the same origin
- http://localhost:8080/healthz returns `{"status":"ok","database":"ok"}` once Postgres answers
- Postgres is also published on `localhost:5432` for `psql` and the backend's `postgres` tests; the superuser is `rakin:rakin`, and the API and migration users are the ones in `.env.example`

Services: `caddy` (the single entry point), `api` (FastAPI), `jobs` (the nightly jobs, checked hourly; see [Nightly jobs](backend/README.md#nightly-jobs)), `postgres`, `web` (the Vite dev server) and a one-shot `migrate` that creates the database users (`python -m app.db_bootstrap`) and runs `alembic upgrade head` before `api` and `jobs` start. Editing `backend/` reloads the API and editing `frontend/` hot-reloads the SPA, with no rebuild. Rebuild the API image (`docker compose up --build`) only after changing `backend/pyproject.toml`.

To try it with data, `make seed` (`docker compose run --rm api python -m app.seed`) loads the demo gym, Academia Sur: 71 members across the adults and kids programs, all five plan kinds, and the paid, overdue, pending-proof and frozen memberships the [UI design](docs/design/ui-design.html) shows. It is safe to re-run; see [Seed data](backend/README.md#seed-data).

Uploads (payment proofs) go to local disk by default, in the `blobs` volume, and email is written to the API's log instead of sent: every integration has a default that needs no account. To store files in S3-compatible storage instead, set `BLOB_STORE=s3`. Self-hosters without a provider add [Garage](https://garagehq.deuxfleurs.fr/): `docker compose --profile selfhost up` also starts it on http://localhost:3900, and a one-shot `garage-init` creates the `rakin` bucket and the API's access key from the `S3_*` values in `.env.example`.

If port 8080 or 5432 is already in use, set `HTTP_PORT` or `POSTGRES_PORT` in `.env`. Containers get only the variables `docker-compose.yml` passes them: the Postgres superuser reaches `migrate` alone, and the API and migration users come from `POSTGRES_API_*` and `POSTGRES_OWNER_*`. `docker compose down` stops the stack; `docker compose down -v` also deletes the database.

To run the API or the SPA on the host instead, see [backend/README.md](backend/README.md) and [frontend/README.md](frontend/README.md).

## Self-hosting

Planned contract: `docker compose up` with `.env.example` works in under 10 minutes, seed data included. Every integration has a local or no-op default.

## Data protection

Whoever runs an instance is the data controller for it under Chile's Ley 21.719. See [Compliance](docs/technical.md#compliance-and-privacy).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Commits need a DCO sign-off (`git commit -s`).

## License

[AGPL-3.0](LICENSE). The name "Rakin" and the rakin.app domain are covered by [TRADEMARK.md](TRADEMARK.md).
