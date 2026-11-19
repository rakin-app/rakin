import argparse
import asyncio
from datetime import date

import asyncpg

from app.db_bootstrap import to_dsn
from app.integrations import build_blob_store
from app.seed import Loaded, load, store_proofs
from app.seed.data import GYM_NAME
from app.settings import Settings, get_settings


def refusal(settings: Settings) -> str | None:
    """Why the demo gym may not be loaded here, or None when it may."""
    if settings.environment == "production" and not settings.seed_only:
        return (
            "refusing to load the demo gym on ENVIRONMENT=production: set SEED_ONLY=1"
            " in this host's .env if it only ever holds seed data (staging)"
        )
    return None


async def run(today: date | None) -> tuple[Loaded, int]:
    settings = get_settings()
    # The owner, as for migrations; RLS holds it to the demo gym all the same.
    conn = await asyncpg.connect(to_dsn(settings.migration_database_url))
    try:
        loaded = await load(conn, today)
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
    args = parser.parse_args()
    if (problem := refusal(get_settings())) is not None:
        parser.exit(2, f"{problem}\n")
    loaded, proofs = asyncio.run(run(args.today))
    if loaded.ignored_today:
        print(
            f"{GYM_NAME} was seeded as of {loaded.seed.as_of};"
            f" --today {loaded.ignored_today} ignored"
        )
    counts = ", ".join(f"{table} {n}" for table, n in loaded.inserted.items())
    print(f"{GYM_NAME} as of {loaded.seed.as_of}: inserted {counts}, proof files {proofs}")


if __name__ == "__main__":
    main()
