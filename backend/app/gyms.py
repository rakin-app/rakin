"""Create a real gym, empty, with its owner (#155). There is no self-service sign-up yet.

    uv run python -m app.gyms create --slug meta --name "Meta" \\
        --timezone America/Santiago \\
        --owner-email … --owner-name … [--owner-rut …] [--owner-phone …] \\
        [--grading <preset key>] \\
        (--processor-terms <version> --signed-on <date> | --no-processor-terms)
    uv run python -m app.gyms sign-terms --slug meta \\
        --processor-terms <version> --signed-on <date>

The gym gets what the demo seed's has before anyone trains there (`app.seed.data`):
its programs and the block kinds every gym is given (0028); a grading scheme only when
`--grading` names a preset (`app.domain.grading`), since grading is a module a gym turns
on, not every sport has one: by default it has no grades and shows no belts. With a
preset it also gets one activity (0043), named as the preset is, that uses grades, so
the belts show, and that activity's words (#344, `app.domain.vocabulary`): what the gym
calls itself, its members and its coach; with none, no activity, which its owner picks
on first sign-in; and its owner, a staff row on the person with that RUT, found or
created as the API adds anyone (`join_gym`, 0036), or with no RUT someone new keyed by
the email. The phone is optional, a contact only. Its slug is its host,
`<slug>.<BASE_DOMAIN>` (`app.hosts`). The owner signs in there with the email given.

Its free-practice block kind (0028's Sparring) takes the activity's name for it, or
"Práctica libre" with none (#346, `app.domain.practice`), so a new gym does not start
as a dojo.

A hosted gym signs the Términos de encargo (`docs/legal/terminos-de-encargo.md`, #367)
before its data goes in: `create` takes the version signed, which must be the current
one, `PROCESSOR_TERMS_VERSION`, and the date on the signed copy, and records them in
`processor_terms` (0075) with the gym. `--no-processor-terms` is for an instance the
company does not host, whose operator is not processing for it. `sign-terms` records a
signature for a gym that already exists: one from before #367, or a new version of the
terms, as a new subprocessor in their Anexo A makes.

Running it again with a slug a gym already has changes nothing, whatever else it is
given, and says so, and points terms given at `sign-terms`, which records them. A
`sign-terms` with a version the gym already signed changes nothing either: the first
date stays. It connects as the table owner, as the seed does: RLS holds it to the new
gym once `app.gym_id` names it.

`create` writes through `gym_create` (0077), which the platform's panel calls too
(`app.api.platform`, #437): what the presets make of the gym is computed here
(`gym_create_values`), and the function only writes it, so the two cannot drift.
"""

import argparse
import asyncio
import copy
import json
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import asyncpg
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from app.db_bootstrap import to_dsn
from app.domain import practice, vocabulary
from app.domain.dates import gym_today
from app.domain.grading import PRESETS
from app.hosts import Hosts, slug_problem
from app.schemas.gym import Timezone
from app.schemas.people import Email, Name, Phone, Rut
from app.settings import get_settings

# The programs every new gym starts with (#347). Not the demo gym's (`app.seed.data`):
# its competition team is a combat school's, and a program is never deleted.
PROGRAMS = ("Adultos", "Niños")

# A preset's key, as `--grading` takes it, to the scheme the gym starts with, and the
# graded activity it starts with: none for the preset with no ranks.
SCHEMES = {preset["key"]: preset["scheme"] for preset in PRESETS}
ACTIVITIES = {
    preset["key"]: preset["label"]
    for preset in PRESETS
    if preset["scheme"]["ranks"] or preset["scheme"]["kids_ladder"]
}


# The "Versión" line of `docs/legal/terminos-de-encargo.md`; a test holds them equal.
# A change to the terms a gym must sign again for gets a new one.
PROCESSOR_TERMS_VERSION = "2026-11-18"
SIGNED_IN = "America/Santiago"


def terms_problem(version: str) -> tuple[str, str] | None:
    """Why `version` cannot be signed, as a code and a message, or None when it can."""
    if version != PROCESSOR_TERMS_VERSION:
        return "terms_version", f"not the current terms, {PROCESSOR_TERMS_VERSION}"
    return None


def signing_problem(signed_on: date) -> tuple[str, str] | None:
    """Why the terms cannot have been signed on `signed_on`, as a code and a message."""
    # The terms are signed in Chile, so a date to come is one past Chile's today.
    if signed_on > gym_today(SIGNED_IN):
        return "signed_on_future", "a date to come"
    if signed_on < date.fromisoformat(PROCESSOR_TERMS_VERSION):
        return "signed_on_early", f"before the terms' version, {PROCESSOR_TERMS_VERSION}"
    return None


class TermsSigned(BaseModel):
    """The Términos de encargo a gym signed, and the date on the signed copy."""

    model_config = ConfigDict(extra="forbid")

    processor_terms: str | None = None
    signed_on: date | None = None

    @field_validator("processor_terms")
    @classmethod
    def _the_current_terms(cls, value: str | None) -> str | None:
        problem = None if value is None else terms_problem(value)
        if problem is not None:
            raise ValueError(problem[1])
        return value

    @field_validator("signed_on")
    @classmethod
    def _signed_since_they_exist(cls, value: date | None) -> date | None:
        problem = None if value is None else signing_problem(value)
        if problem is not None:
            raise ValueError(problem[1])
        return value

    @model_validator(mode="after")
    def _both_or_neither(self) -> "TermsSigned":
        if (self.processor_terms is None) != (self.signed_on is None):
            raise ValueError("--processor-terms and --signed-on go together")
        return self


class NewGym(TermsSigned):
    slug: str
    name: Name
    timezone: Timezone
    owner_email: Email
    owner_name: Name
    owner_rut: Rut | None = None
    owner_phone: Phone | None = None
    grading: str = "none"

    @field_validator("slug")
    @classmethod
    def _a_host_label(cls, value: str) -> str:
        problem = slug_problem(value)
        if problem is not None:
            raise ValueError(problem)
        return value

    @field_validator("grading")
    @classmethod
    def _a_preset(cls, value: str) -> str:
        if value not in SCHEMES:
            raise ValueError(f"not a grading preset: one of {', '.join(SCHEMES)}")
        return value


class Signing(TermsSigned):
    slug: str
    processor_terms: str
    signed_on: date


@dataclass(frozen=True)
class Created:
    gym_id: uuid.UUID
    name: str
    # False when a gym already had the slug, and nothing was written.
    created: bool


def settings_of(grading: str) -> dict[str, object]:
    """The new gym's `gym.settings`: its scheme and, with a graded activity, its words."""
    settings: dict[str, object] = {"grading": copy.deepcopy(SCHEMES[grading])}
    if grading in ACTIVITIES:
        words = vocabulary.words_of(vocabulary.GRADING_PRESETS.get(grading))
        settings["vocabulary"] = vocabulary.stored(words, by_hand=False)
    return settings


def gym_create_values(gym: NewGym, gym_id: uuid.UUID) -> tuple[object, ...]:
    """`gym`'s arguments to `gym_create` (0077), in its order: what the presets make of
    it computed here, so the command line and the panel write the same gym."""
    preset = vocabulary.GRADING_PRESETS.get(gym.grading)
    return (
        gym_id,
        gym.slug,
        gym.name,
        gym.timezone,
        json.dumps(settings_of(gym.grading)),
        list(PROGRAMS),
        ACTIVITIES.get(gym.grading),
        preset,
        # The practice's kind, as its activity names it, else "Práctica libre" (#346).
        practice.practice_of([preset]).block,
        gym.owner_email,
        gym.owner_name,
        gym.owner_rut,
        gym.owner_phone,
        gym.processor_terms,
        gym.signed_on,
    )


async def create_gym(conn: asyncpg.Connection, gym: NewGym) -> Created:
    """Write `gym` and its owner in one transaction, unless its slug is taken."""
    row = await conn.fetchrow(
        "SELECT id, name, created FROM gym_create("
        "$1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)",
        *gym_create_values(gym, uuid.uuid4()),
    )
    return Created(row["id"], row["name"], created=row["created"])


async def record_terms(
    conn: asyncpg.Connection, gym_id: uuid.UUID, version: str, signed_on: date | None
) -> bool:
    """Record that the gym `app.gym_id` names signed `version`; `False` if it had."""
    recorded = await conn.fetchval(
        "INSERT INTO processor_terms (gym_id, version, signed_on) VALUES ($1, $2, $3)"
        " ON CONFLICT (gym_id, version) DO NOTHING RETURNING true",
        gym_id,
        version,
        signed_on,
    )
    return bool(recorded)


@dataclass(frozen=True)
class Signed:
    gym_id: uuid.UUID
    name: str
    # False when the gym had signed this version already, and nothing was written.
    recorded: bool


async def sign_terms(conn: asyncpg.Connection, signing: Signing) -> Signed | None:
    """Record `signing` for the gym with its slug; `None` if no gym has it."""
    async with conn.transaction():
        found = await conn.fetchrow("SELECT id, name FROM auth_gym_by_slug($1)", signing.slug)
        if found is None:
            return None
        await conn.execute("SELECT set_config('app.gym_id', $1, true)", str(found["id"]))
        recorded = await record_terms(conn, found["id"], signing.processor_terms, signing.signed_on)
    return Signed(found["id"], found["name"], recorded)


async def run(command: NewGym | Signing) -> Created | Signed | None:
    conn = await asyncpg.connect(to_dsn(get_settings().migration_database_url))
    try:
        if isinstance(command, Signing):
            return await sign_terms(conn, command)
        return await create_gym(conn, command)
    finally:
        await conn.close()


def _add_terms(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument(
        "--processor-terms",
        required=required,
        metavar="VERSION",
        help=f"the Términos de encargo signed: their version, {PROCESSOR_TERMS_VERSION}",
    )
    parser.add_argument(
        "--signed-on",
        required=required,
        metavar="YYYY-MM-DD",
        help="the date on the signed copy",
    )


def parse(argv: Sequence[str] | None = None) -> NewGym | Signing:
    parser = argparse.ArgumentParser(description="Manage real gyms.")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="create an empty gym and its owner")
    create.add_argument("--slug", required=True, help="its host: <slug>.<BASE_DOMAIN>")
    create.add_argument("--name", required=True)
    create.add_argument("--timezone", default="America/Santiago")
    create.add_argument("--owner-email", required=True)
    create.add_argument("--owner-name", required=True)
    create.add_argument("--owner-rut")
    create.add_argument("--owner-phone")
    create.add_argument(
        "--grading",
        default="none",
        help=f"a grading preset to start from: {', '.join(SCHEMES)}",
    )
    _add_terms(create, required=False)
    create.add_argument(
        "--no-processor-terms",
        action="store_true",
        help="on an instance the company does not host: no Términos de encargo to sign",
    )
    sign = commands.add_parser(
        "sign-terms", help="record that a gym signed the Términos de encargo"
    )
    sign.add_argument("--slug", required=True)
    _add_terms(sign, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "sign-terms":
            return Signing(
                slug=args.slug, processor_terms=args.processor_terms, signed_on=args.signed_on
            )
        if args.no_processor_terms == (args.processor_terms is not None):
            create.error(
                "a hosted gym signs the Términos de encargo before its data goes in:"
                " give --processor-terms and --signed-on, or --no-processor-terms"
                " on an instance the company does not host"
            )
        return NewGym(
            slug=args.slug,
            name=args.name,
            timezone=args.timezone,
            owner_email=args.owner_email,
            owner_name=args.owner_name,
            owner_rut=args.owner_rut,
            owner_phone=args.owner_phone,
            grading=args.grading,
            processor_terms=args.processor_terms,
            signed_on=args.signed_on,
        )
    except ValidationError as error:
        for problem in error.errors():
            field = "--" + "-".join(str(p) for p in problem["loc"]).replace("_", "-")
            # A model-level problem has no field: its message names the flags.
            message = f"{field}: {problem['msg']}" if problem["loc"] else problem["msg"]
            print(message, file=sys.stderr)
        raise SystemExit(2) from None


def main(argv: Sequence[str] | None = None) -> None:
    gym = parse(argv)
    done = asyncio.run(run(gym))
    if isinstance(gym, Signing):
        if done is None:
            print(f"no gym has the slug {gym.slug}", file=sys.stderr)
            raise SystemExit(1)
        assert isinstance(done, Signed)
        if done.recorded:
            print(f"{done.name} signed the Términos de encargo {gym.processor_terms}")
        else:
            print(f"{done.name} had signed {gym.processor_terms}: nothing changed")
        return
    assert isinstance(done, Created)
    created = done
    url = Hosts.of(get_settings()).base_url(gym.slug)
    if created.created:
        print(f"{created.name} created ({created.gym_id}), at {url}")
    else:
        print(f"{gym.slug} is already {created.name} ({created.gym_id}): nothing changed")
        if gym.processor_terms is not None:
            print(
                f"the Términos de encargo were not recorded either: for a gym that exists,"
                f" use sign-terms --slug {gym.slug}"
            )


if __name__ == "__main__":
    main()
