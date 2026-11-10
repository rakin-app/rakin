"""Create a real gym, empty, with its owner (#155). There is no self-service sign-up yet.

    uv run python -m app.gyms create --slug meta --name "Meta" \\
        --timezone America/Santiago \\
        --owner-email … --owner-name … --owner-phone …

The gym gets what the demo seed's has before anyone trains there (`app.seed.data`):
its grading scheme, its programs, and the block kinds every gym is given (0028); and
its owner, a staff row on the person with that phone, found or created as the API adds
anyone (`join_gym_by_phone`, 0004). Its slug is its host, `<slug>.<BASE_DOMAIN>`
(`app.hosts`). The owner signs in there with the email given.

Running it again with a slug a gym already has changes nothing, whatever else it is
given, and says so. It connects as the table owner, as the seed does: RLS holds it to
the new gym once `app.gym_id` names it.
"""

import argparse
import asyncio
import copy
import json
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import asyncpg
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.db_bootstrap import to_dsn
from app.hosts import Hosts, slug_problem
from app.roles import Role
from app.schemas.gym import Timezone
from app.schemas.people import Email, Name, Phone
from app.seed.data import GRADING, PROGRAMS
from app.settings import get_settings


class NewGym(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: Name
    timezone: Timezone
    owner_email: Email
    owner_name: Name
    owner_phone: Phone

    @field_validator("slug")
    @classmethod
    def _a_host_label(cls, value: str) -> str:
        problem = slug_problem(value)
        if problem is not None:
            raise ValueError(problem)
        return value


@dataclass(frozen=True)
class Created:
    gym_id: uuid.UUID
    name: str
    # False when a gym already had the slug, and nothing was written.
    created: bool


async def create_gym(conn: asyncpg.Connection, gym: NewGym) -> Created:
    """Write `gym` and its owner in one transaction, unless its slug is taken."""
    async with conn.transaction():
        found = await conn.fetchrow("SELECT id, name FROM auth_gym_by_slug($1)", gym.slug)
        if found is not None:
            return Created(found["id"], found["name"], created=False)
        gym_id = uuid.uuid4()
        # RLS is forced, so the owner writes only in the gym `app.gym_id` names.
        await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(gym_id))
        # The block kinds come with the row (0028's trigger).
        await conn.execute(
            "INSERT INTO gym (id, name, slug, timezone, settings)"
            " VALUES ($1, $2, $3, $4, $5::jsonb)",
            gym_id,
            gym.name,
            gym.slug,
            gym.timezone,
            json.dumps({"grading": copy.deepcopy(GRADING)}),
        )
        await conn.executemany(
            "INSERT INTO program (gym_id, name) VALUES ($1, $2)",
            [(gym_id, name) for name in PROGRAMS.values()],
        )
        person_id = await conn.fetchval(
            "SELECT person_id FROM join_gym_by_phone($1, $2, $3, NULL, NULL)",
            gym.owner_phone,
            gym.owner_name,
            gym.owner_email,
        )
        await conn.execute(
            "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, $3)",
            gym_id,
            person_id,
            Role.OWNER.value,
        )
    return Created(gym_id, gym.name, created=True)


async def run(gym: NewGym) -> Created:
    conn = await asyncpg.connect(to_dsn(get_settings().migration_database_url))
    try:
        return await create_gym(conn, gym)
    finally:
        await conn.close()


def parse(argv: Sequence[str] | None = None) -> NewGym:
    parser = argparse.ArgumentParser(description="Manage real gyms.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="create an empty gym and its owner")
    create.add_argument("--slug", required=True, help="its host: <slug>.<BASE_DOMAIN>")
    create.add_argument("--name", required=True)
    create.add_argument("--timezone", default="America/Santiago")
    create.add_argument("--owner-email", required=True)
    create.add_argument("--owner-name", required=True)
    create.add_argument("--owner-phone", required=True)
    args = parser.parse_args(argv)
    try:
        return NewGym(
            slug=args.slug,
            name=args.name,
            timezone=args.timezone,
            owner_email=args.owner_email,
            owner_name=args.owner_name,
            owner_phone=args.owner_phone,
        )
    except ValidationError as error:
        for problem in error.errors():
            field = "--" + "-".join(str(p) for p in problem["loc"]).replace("_", "-")
            print(f"{field}: {problem['msg']}", file=sys.stderr)
        raise SystemExit(2) from None


def main(argv: Sequence[str] | None = None) -> None:
    gym = parse(argv)
    created = asyncio.run(run(gym))
    url = Hosts.of(get_settings()).base_url(gym.slug)
    if created.created:
        print(f"{created.name} created ({created.gym_id}), at {url}")
    else:
        print(f"{gym.slug} is already {created.name} ({created.gym_id}): nothing changed")


if __name__ == "__main__":
    main()
