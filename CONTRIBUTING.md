# Contributing to Rakin

Thanks for your interest. Rakin is small and opinionated. Please read the [product principles](docs/product.md#product-principles-and-non-goals) before proposing a feature. Anything in the non-goals list will be declined.

## Ground rules

- **The ledger is append-only.** Never update or delete a `ledger_entry`; corrections are new entries.
- **No sport-specific code paths.** Sport variance lives in grading schemes, plan kinds and custom fields.
- **Money is integer CLP.** No floats, no decimals.
- **Time is UTC in the database.** All due-date math uses `gym.timezone`.
- **Every tenant table has `gym_id` and an RLS policy.** Tests must prove cross-gym reads return nothing.
- **Migrations are forward-only and additive within a release.**
- **Integrations sit behind an interface with a local or no-op default** (`PaymentRail`, `BankFeed`, `Messenger`, `Mailer`, `BlobStore`).

## Workflow

1. Pick an issue from the [board](https://github.com/orgs/rakin-app/projects) or open one first for anything non-trivial.
2. Branch from `main`, keep PRs focused, and link the issue (`Closes #123`).
3. CI runs migrations and tests against a real Postgres. It must be green.
4. User-facing strings go in the Spanish i18n file, never inline.

## Developer Certificate of Origin

We use the [DCO](https://developercertificate.org/) instead of a CLA. Sign off every commit:

```sh
git commit -s -m "Add freeze due-date shift"
```

This adds `Signed-off-by: Your Name <you@example.com>` and certifies that you have the right to submit the work under AGPL-3.0.

## Reporting security issues

Do not open a public issue. Email soporte@rakin.app.
