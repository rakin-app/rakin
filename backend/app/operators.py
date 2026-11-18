"""Who may use the platform's panel (#436): grant, revoke and list its operators.

    uv run python -m app.operators grant --email … --name …
    uv run python -m app.operators revoke --email …
    uv run python -m app.operators list

An operator signs in at `/plataforma` on the base host (`app.platform`) and sees every
gym Rakin hosts, so the list of them is kept here, on the host's shell, and no screen
ever grants or revokes. It connects as the table owner, as `app.gyms` does: the API's
role has no privilege on `platform_operator` (migration 0076).

`grant` makes an address an operator, or one revoked an operator again; for one who
already is, it changes nothing. `revoke` ends them, and ends every session they have
at once. Both write their `platform_event`, with no operator (`detail.by = 'cli'`).
An address is kept lower-case.
"""

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import asyncpg
from pydantic import BaseModel, ValidationError

from app.db_bootstrap import to_dsn
from app.schemas.people import Email, Name
from app.settings import get_settings


class Grant(BaseModel):
    email: Email
    name: Name


class Revoke(BaseModel):
    email: Email


class Listing(BaseModel):
    pass


Command = Grant | Revoke | Listing


@dataclass(frozen=True)
class Operator:
    id: uuid.UUID
    email: str
    name: str
    granted_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class Done:
    """What a grant or revoke did: `changed` False when there was nothing to do,
    `operator` None when no operator has the address."""

    operator: Operator | None
    changed: bool
    sessions_ended: int = 0


SELECT = "SELECT id, email, name, granted_at, revoked_at FROM platform_operator"


def _detail(operator_id: uuid.UUID, **more: object) -> str:
    return json.dumps({"by": "cli", "operator_id": str(operator_id), **more})


async def grant(conn: asyncpg.Connection, command: Grant) -> Done:
    email = command.email.lower()
    async with conn.transaction():
        found = await conn.fetchrow(f"{SELECT} WHERE email = $1 FOR UPDATE", email)
        if found is not None and found["revoked_at"] is None:
            return Done(Operator(**found), changed=False)
        row = await conn.fetchrow(
            "INSERT INTO platform_operator (email, name) VALUES ($1, $2)"
            " ON CONFLICT (email) DO UPDATE"
            " SET name = EXCLUDED.name, granted_at = now(), revoked_at = NULL"
            " RETURNING id, email, name, granted_at, revoked_at",
            email,
            command.name,
        )
        await conn.execute(
            "INSERT INTO platform_event (action, detail) VALUES ('operator_granted', $1::jsonb)",
            _detail(row["id"]),
        )
    return Done(Operator(**row), changed=True)


async def revoke(conn: asyncpg.Connection, command: Revoke) -> Done:
    async with conn.transaction():
        found = await conn.fetchrow(f"{SELECT} WHERE email = $1 FOR UPDATE", command.email.lower())
        if found is None:
            return Done(None, changed=False)
        if found["revoked_at"] is not None:
            return Done(Operator(**found), changed=False)
        row = await conn.fetchrow(
            "UPDATE platform_operator SET revoked_at = now() WHERE id = $1"
            " RETURNING id, email, name, granted_at, revoked_at",
            found["id"],
        )
        ended = await conn.fetch(
            "UPDATE operator_session SET ended_at = now()"
            " WHERE operator_id = $1 AND ended_at IS NULL AND expires_at > now()"
            " RETURNING 1",
            found["id"],
        )
        await conn.execute(
            "INSERT INTO platform_event (action, detail) VALUES ('operator_revoked', $1::jsonb)",
            _detail(found["id"], sessions_ended=len(ended)),
        )
    return Done(Operator(**row), changed=True, sessions_ended=len(ended))


async def operators(conn: asyncpg.Connection) -> list[Operator]:
    return [Operator(**row) for row in await conn.fetch(f"{SELECT} ORDER BY email")]


async def run(command: Command) -> Done | list[Operator]:
    conn = await asyncpg.connect(to_dsn(get_settings().migration_database_url))
    try:
        if isinstance(command, Grant):
            return await grant(conn, command)
        if isinstance(command, Revoke):
            return await revoke(conn, command)
        return await operators(conn)
    finally:
        await conn.close()


def parse(argv: Sequence[str] | None = None) -> Command:
    parser = argparse.ArgumentParser(description="Manage the platform's operators.")
    commands = parser.add_subparsers(dest="command", required=True)
    granting = commands.add_parser("grant", help="let an address sign in to /plataforma")
    granting.add_argument("--email", required=True)
    granting.add_argument("--name", required=True)
    revoking = commands.add_parser("revoke", help="end an operator, and their sessions")
    revoking.add_argument("--email", required=True)
    commands.add_parser("list", help="every operator, revoked ones included")
    args = parser.parse_args(argv)
    try:
        if args.command == "grant":
            return Grant(email=args.email, name=args.name)
        if args.command == "revoke":
            return Revoke(email=args.email)
        return Listing()
    except ValidationError as error:
        for problem in error.errors():
            print(f"--{problem['loc'][0]}: {problem['msg']}", file=sys.stderr)
        raise SystemExit(2) from None


def main(argv: Sequence[str] | None = None) -> None:
    command = parse(argv)
    done = asyncio.run(run(command))
    if isinstance(done, list):
        for each in done:
            state = "active" if each.revoked_at is None else f"revoked {each.revoked_at:%Y-%m-%d}"
            print(f"{each.email}\t{each.name}\tgranted {each.granted_at:%Y-%m-%d}\t{state}")
        return
    if isinstance(command, Revoke) and done.operator is None:
        print(f"no operator has the address {command.email}", file=sys.stderr)
        raise SystemExit(1)
    operator = done.operator
    assert operator is not None
    if isinstance(command, Grant):
        if done.changed:
            print(f"{operator.email} ({operator.name}) may now sign in at /plataforma")
        else:
            print(f"{operator.email} is already an operator: nothing changed")
        return
    if done.changed:
        print(f"{operator.email} revoked; {done.sessions_ended} session(s) ended")
    else:
        print(f"{operator.email} was already revoked: nothing changed")


if __name__ == "__main__":
    main()
