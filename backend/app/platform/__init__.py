"""The platform's operators (#433, #436): the people who run the gyms Rakin hosts.

An operator is granted from the host's shell (`app.operators`), never from a screen,
and signs in on the base host only, at `/plataforma`, with a link and its code as
anyone signs in to a gym (`app.magiclink`). Everything else is kept apart from a gym's
sign-in: their own tables (migration 0076), their own cookie, `__Host-platform`, and a
session of 8 hours from sign-in, never extended. So a gym's session never reaches the
panel and an operator's never reaches a gym.

- `app.platform.session`: the `OperatorSession` every panel endpoint takes, and
  `require_fresh` for the actions that need a recent proof.
- `app.platform.web`: the sign-in endpoints, under `/api/platform/auth`.

The database holds the gate too: every function that reads or writes a gym checks the
session it is given (0076), whatever the API asked.
"""
