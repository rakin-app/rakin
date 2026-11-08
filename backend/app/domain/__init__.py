"""Pure domain rules and helpers: no I/O, no ORM, no framework.

CLP money, gym-timezone date math, RUT and phone numbers, and the membership and
ledger-entry state machines. Every module is tested in isolation; the tests in
`tests/domain` are the contract the ORM models and services must keep
(docs/technical.md#core-state-machines).
"""
