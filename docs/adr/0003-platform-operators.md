# ADR 0003: Platform operators are their own accounts, cookie and database role

- **Status:** accepted
- **Date:** 2026-11-18
- **Issue:** #436 (epic #433)

## Context

Until now nobody stood outside the gyms. A gym is created with `python -m app.gyms
create` over SSH, and every person who signs in belongs to some gym: the sign-in
lookups find only people a gym has (`auth_people_by_email`, migration 0042), and a
session acts in one gym at a time.

The platform's owner wants a panel to list, create, edit and suspend the gyms Rakin
hosts (#433). That panel is the one place in the product that looks across gyms. The
API's database role, `rakin_app`, sees one gym at a time under RLS (`app.gym_id`), and
that is the property every other screen relies on: a missed `WHERE` returns nothing
rather than another gym's data. The panel needs a way across gyms that does not
weaken it.

## Decision

**Operators are their own accounts.** `platform_operator` (migration 0076) holds who
may use the panel, granted and revoked only from the host's shell (`python -m
app.operators grant|revoke|list`, as the table's owner). No screen grants. An operator
is no gym's person: a gym owner is not an operator unless granted, and an operator
gains nothing in any gym.

**Their own sign-in and cookie.** The flow is a gym's (`app.magiclink`: a link with a
button and a six-digit code), served by the same router, but its links and sessions
live in `operator_link` and `operator_session`, and its cookie is `__Host-platform`,
not `__Host-session`. So a gym's session never authenticates in the panel, and an
operator's never authenticates in a gym: each side reads only its own cookie. The
session lasts 8 hours from sign-in, never extended; the irreversible actions of later
tickets also ask for a proof within 10 minutes (`require_fresh`). The panel is the
base host's alone: `/api/platform/*` answers 404 on a gym's host.

**Their own database role, and the gate inside each function.** The API never reads
the platform's tables and never lifts RLS. Everything the panel does goes through
`SECURITY DEFINER` functions owned by `rakin_platform`, a NOLOGIN role with BYPASSRLS
created by `app.db_bootstrap` as `rakin_auth` is, with grants on only the columns
those functions read. **Each function that reads or writes a gym takes the operator's
session hash and checks, itself, that the session is live** (`platform_operator_of`),
and raises otherwise. The API's `OperatorSession` checks the same session first, to
answer 401 and 404 properly, but it is not what keeps the data in.

**An append-only log.** `platform_event` records sign-in and sign-out, grant and
revoke, and every write of the later tickets, with no foreign key on `gym_id` so a row
outlives a removed gym. Nothing updates or deletes it, the owner included.

## Consequences

- A bug in an API endpoint, or an endpoint that forgets `OperatorSession`, still reads
  no gym across tenants: `rakin_app` holds no privilege that would, and the functions
  refuse without a live operator session.
- Two cookies and two session tables to reason about, and a second router built on
  `app.magiclink`'s (`Links`, the protocol it now takes, lets an application issue its
  own links).
- Revoking an operator ends their sessions at once: the session check joins the
  operator's `revoked_at`, and `revoke` ends their sessions too.
- Granting needs shell access to the host. That is deliberate for now: the list of
  operators is short and changes rarely.
- Every new panel action needs a new `platform_*` function, its gate and its event:
  more SQL than an endpoint would need, in exchange for the gate holding in the
  database.
