import argparse
import asyncio
from datetime import date

import asyncpg

from app.db_bootstrap import to_dsn
from app.integrations import build_blob_store
from app.seed import Loaded, load, store_proofs
from app.seed.build import seed_id, sign_in_addresses
from app.seed.data import GYM_NAME, SIGN_IN_PEOPLE
from app.settings import Settings, get_settings


def refusal(settings: Settings) -> str | None:
    """Why the demo gym may not be loaded here, or None when it may."""
    if settings.environment == "production" and not settings.seed_only:
        return (
            "refusing to load the demo gym on ENVIRONMENT=production: set SEED_ONLY=1"
            " in this host's .env if it only ever holds seed data (staging)"
        )
    return None


async def run(today: date | None, sign_in: list[str]) -> tuple[Loaded, int]:
    settings = get_settings()
    # The owner, as for migrations; RLS holds it to the demo gym all the same.
    conn = await asyncpg.connect(to_dsn(settings.migration_database_url))
    try:
        loaded = await load(conn, today, sign_in)
    finally:
        await conn.close()
    return loaded, await store_proofs(loaded.seed, build_blob_store(settings))


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Load the demo gym, {GYM_NAME}.")
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        help="the gym-local date the data depicts, YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--sign-in",
        type=lambda value: value.split(","),
        default=[],
        metavar="ADDRESS,...",
        help="addresses that replace seed people's own, so they can sign in by code:"
        " the first a student who owes, the second the owner (staging's STAGING_OPERATORS)",
    )
    args = parser.parse_args()
    if (problem := refusal(get_settings())) is not None:
        parser.exit(2, f"{problem}\n")
    loaded, proofs = asyncio.run(run(args.today, args.sign_in))
    if loaded.ignored_today:
        print(
            f"{GYM_NAME} was seeded as of {loaded.seed.as_of};"
            f" --today {loaded.ignored_today} ignored"
        )
    counts = ", ".join(f"{table} {n}" for table, n in loaded.inserted.items())
    print(f"{GYM_NAME} as of {loaded.seed.as_of}: inserted {counts}, proof files {proofs}")
    for line in sign_in_lines(loaded, args.sign_in):
        print(line)


def sign_in_lines(loaded: Loaded, sign_in: list[str]) -> list[str]:
    """Who each `--sign-in` address became. A reload writes no person, so it says the
    addresses are not there."""
    if not (people := sign_in_addresses(sign_in)):
        return []
    if loaded.inserted.get("person", 0) == 0:
        return ["--sign-in ignored: the people were already there; reset the database first"]
    roles = dict(SIGN_IN_PEOPLE)
    names = {p["id"]: p["name"] for p in loaded.seed.people}
    return [
        f"sign in as {names[seed_id('person', key)]} ({roles[key]}): {address}"
        for key, address in people.items()
    ]


if __name__ == "__main__":
    main()
