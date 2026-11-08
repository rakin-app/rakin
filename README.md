# Rakin

**[Español](README.es.md)** · English

Rakin (*Mapudungun: to count*) is an open-source, sport-agnostic membership and fee-tracking platform for small martial-arts gyms. It replaces the spreadsheet plus WhatsApp group that most gyms run on.

The core loop: **member → plan → due date → reminder → bank transfer arrives → validated in the ledger → silence.** Rakin never processes money in v1. It tracks, reminds and reconciles transfers the gym already receives.

> **Status:** pre-alpha. Nothing to run yet. Follow the [roadmap](https://github.com/orgs/rakin-app/projects) and [milestones](https://github.com/rakin-app/rakin/milestones).

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

## Self-hosting

Planned contract: `docker compose up` with `.env.example` works in under 10 minutes, seed data included. Every integration has a local or no-op default.

## Data protection

Whoever runs an instance is the data controller for it under Chile's Ley 21.719. See [Compliance](docs/technical.md#compliance-and-privacy).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Commits need a DCO sign-off (`git commit -s`).

## License

[AGPL-3.0](LICENSE). The name "Rakin" and the rakin.app domain are covered by [TRADEMARK.md](TRADEMARK.md).
