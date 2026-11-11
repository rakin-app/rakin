import argparse
import asyncio
from datetime import date

import asyncpg

from app.db_bootstrap import to_dsn
from app.integrations import build_blob_store
from app.seed import Loaded, load, store_proofs
from app.seed.data import GYM_NAME
from app.settings import get_settings


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
    loaded, proofs = asyncio.run(run(parser.parse_args().today))
    if loaded.ignored_today:
        print(
            f"{GYM_NAME} was seeded as of {loaded.seed.as_of};"
            f" --today {loaded.ignored_today} ignored"
        )
    counts = ", ".join(f"{table} {n}" for table, n in loaded.inserted.items())
    print(f"{GYM_NAME} as of {loaded.seed.as_of}: inserted {counts}, proof files {proofs}")


if __name__ == "__main__":
    main()
