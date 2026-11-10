"""Nightly database backups: `pg_dump`, encrypted with age, in their own bucket.

    python -m app.backup run              # one backup now; non-zero if it failed
    python -m app.backup serve --at 03:00 # every night at that time (JOBS_TIMEZONE)
    python -m app.backup list             # the backups in the bucket, newest first
    python -m app.backup fetch <key|latest> <path>   # download one, still encrypted
    python -m app.backup status           # the last success; non-zero if over 26 hours ago

Compose's `backup` service runs `serve`. Each backup is `pg_dump --format=custom` piped
straight into `age` to the public key in `BACKUP_AGE_RECIPIENT`, so the plain dump never
touches the disk and the host cannot decrypt what it wrote: the private key lives in the
password manager. It is uploaded as `rakin/<BACKUP_ENV>/<UTC timestamp>.dump.age` to the
bucket in `BACKUP_S3_*`, its own bucket with its own token, never the app's.

After each upload the job deletes what retention no longer keeps: the newest dump of each
of the 14 most recent days that have one, plus the newest of each of the 8 most recent
Sundays (by the UTC date in the key). It counts dumps, not days since today, so a job
that stops working never ages the last good backups away.

A failure is logged at `ERROR`, which Sentry reports (`app.sentry`), and `serve` tries
again every hour until one succeeds. Each success writes its time and key to
`BACKUP_STATE_DIR/last_success`, which `status` reads. A failure to prune after a
successful upload is only a warning, in the log and in Sentry: the backup is in the bucket.

Postgres comes from the libpq variables (`PGHOST`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`):
the superuser, because several tables force row-level security even on their owner.
`deploy/restore.sh` is the other half: it restores a backup into a scratch database.
"""

import argparse
import logging
import re
import signal
import subprocess
import tempfile
import threading
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sentry_sdk
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.integrations.blobstore import s3_client
from app.logging import configure_logging
from app.sentry import init_sentry

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

DAILY = 14
WEEKLY = 8
# How often `serve` wakes: after a failed night it tries again on each of these ticks
# until a backup succeeds, rather than waiting for the next night.
TICK = timedelta(hours=1)
# A last success older than this is retried on the next tick.
OVERDUE = timedelta(days=1)
# `status` calls a backup stale after a missed night, with an hour's slack.
STALE_AFTER = timedelta(hours=26)

STAMP = "%Y%m%dT%H%M%SZ"
NAME = re.compile(r"(\d{8}T\d{6}Z)\.dump\.age")

DUMP = ("pg_dump", "--format=custom")


def encrypt_command(recipient: str) -> list[str]:
    return ["age", "--encrypt", "--recipient", recipient]


class BackupSettings(BaseSettings):
    """The `backup` service's settings, from its environment only: never a `.env` file."""

    model_config = SettingsConfigDict(extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"
    sentry_dsn: str = ""
    jobs_timezone: str = "America/Santiago"
    # `staging` or `production`: the folder this host's dumps go in.
    backup_env: str = Field(pattern=r"^[a-z0-9-]+$")
    backup_age_recipient: str = Field(pattern=r"^age1[0-9a-z]+$")
    backup_s3_endpoint_url: str
    backup_s3_region: str = "auto"
    backup_s3_bucket: str
    backup_s3_access_key_id: str
    backup_s3_secret_access_key: str
    backup_state_dir: Path = Path("/var/lib/rakin-backup")

    @field_validator("jobs_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone: {value!r}") from exc
        return value

    @property
    def prefix(self) -> str:
        return f"rakin/{self.backup_env}/"


class BackupError(Exception):
    pass


def object_key(prefix: str, at: datetime) -> str:
    return f"{prefix}{at.astimezone(UTC).strftime(STAMP)}.dump.age"


def taken_at(key: str, prefix: str) -> datetime | None:
    """When the backup at `key` was taken; None for anything that is not one of ours."""
    if not key.startswith(prefix):
        return None
    match = NAME.fullmatch(key.removeprefix(prefix))
    if not match:
        return None
    return datetime.strptime(match[1], STAMP).replace(tzinfo=UTC)


def expired(keys: Iterable[str], prefix: str, daily: int = DAILY, weekly: int = WEEKLY) -> set[str]:
    """The backups retention no longer keeps: all but the newest of each of the `daily`
    most recent days, and of each of the `weekly` most recent Sundays."""
    stamped = {key: at for key in keys if (at := taken_at(key, prefix))}
    newest: dict[date, str] = {}
    for key, at in sorted(stamped.items(), key=lambda item: item[1]):
        newest[at.date()] = key
    days = sorted(newest, reverse=True)
    sundays = [day for day in days if day.weekday() == 6]
    keep = {newest[day] for day in days[:daily]} | {newest[day] for day in sundays[:weekly]}
    return stamped.keys() - keep


def client(settings: BackupSettings) -> "S3Client":
    return s3_client(
        settings.backup_s3_endpoint_url,
        settings.backup_s3_region,
        settings.backup_s3_access_key_id,
        settings.backup_s3_secret_access_key,
    )


def backups(s3: "S3Client", settings: BackupSettings) -> list[tuple[str, int]]:
    """Every backup in the bucket as `(key, size)`, newest first."""
    found: list[tuple[datetime, str, int]] = []
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=settings.backup_s3_bucket, Prefix=settings.prefix
    )
    for page in pages:
        for obj in page.get("Contents", []):
            if at := taken_at(obj["Key"], settings.prefix):
                found.append((at, obj["Key"], obj["Size"]))
    return [(key, size) for _, key, size in sorted(found, reverse=True)]


def dump_encrypted(path: Path, recipient: str) -> None:
    """`pg_dump` piped into `age`, written to `path`: the plain dump never hits the disk."""
    with path.open("wb") as out:
        dump = subprocess.Popen(DUMP, stdout=subprocess.PIPE)
        assert dump.stdout is not None
        try:
            encrypt = subprocess.run(encrypt_command(recipient), stdin=dump.stdout, stdout=out)
        finally:
            dump.stdout.close()
            dump_status = dump.wait()
    if dump_status != 0:
        raise BackupError(f"pg_dump exited with {dump_status}")
    if encrypt.returncode != 0:
        raise BackupError(f"age exited with {encrypt.returncode}")


def run_once(settings: BackupSettings, now: datetime) -> str:
    """Take, upload and prune; the new backup's key. A failure to prune is reported but
    does not fail the backup: by then it is safely in the bucket."""
    s3 = client(settings)
    key = object_key(settings.prefix, now)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "backup.dump.age"
        dump_encrypted(path, settings.backup_age_recipient)
        size = path.stat().st_size
        s3.upload_file(str(path), settings.backup_s3_bucket, key)
    settings.backup_state_dir.mkdir(parents=True, exist_ok=True)
    (settings.backup_state_dir / "last_success").write_text(f"{now.isoformat()} {key}\n")
    logger.info("backup uploaded", extra={"key": key, "bytes": size})
    try:
        gone = prune(s3, settings)
    except Exception as exc:
        logger.warning("backup retention failed; the backup itself is uploaded", exc_info=True)
        # A warning, so the logging integration (events from ERROR up) would not send it.
        with sentry_sdk.new_scope() as scope:
            scope.set_level("warning")
            sentry_sdk.capture_exception(exc)
    else:
        logger.info("backup retention applied", extra={"deleted": gone})
    return key


def prune(s3: "S3Client", settings: BackupSettings) -> list[str]:
    """Delete the backups retention no longer keeps; their keys."""
    gone = sorted(expired((k for k, _ in backups(s3, settings)), settings.prefix))
    for old in gone:
        s3.delete_object(Bucket=settings.backup_s3_bucket, Key=old)
    return gone


def attempt(settings: BackupSettings) -> bool:
    """One backup, failure logged (and so reported to Sentry); whether it worked."""
    try:
        run_once(settings, datetime.now(UTC))
    except Exception:
        logger.exception("backup failed")
        return False
    return True


def last_success(settings: BackupSettings) -> datetime | None:
    try:
        text = (settings.backup_state_dir / "last_success").read_text()
    except FileNotFoundError:
        return None
    return datetime.fromisoformat(text.split()[0])


def next_run(now: datetime, at: time, tz: ZoneInfo) -> datetime:
    """The first `at` in `tz` strictly after `now`."""
    local = now.astimezone(tz)
    candidate = datetime.combine(local.date(), at, tz)
    if candidate <= local:
        candidate = datetime.combine(local.date() + timedelta(days=1), at, tz)
    return candidate


def overdue(settings: BackupSettings, now: datetime) -> bool:
    last = last_success(settings)
    return last is None or now - last > OVERDUE


def serve(
    settings: BackupSettings, at: time, stop: threading.Event, tick: timedelta = TICK
) -> None:
    """A backup every night at `at`, until `stop`. Between nights it wakes every `tick`,
    and backs up whenever the last success is over a day old: at once on a new host or
    after one that was down at that hour, and again on each tick after a failed night."""
    tz = ZoneInfo(settings.jobs_timezone)
    logger.info("backup scheduler started", extra={"at": at.isoformat(), "tz": tz.key})
    due = next_run(datetime.now(UTC), at, tz)
    if overdue(settings, datetime.now(UTC)):
        attempt(settings)
    while not stop.is_set():
        wake = min(due, datetime.now(UTC) + tick)
        if stop.wait(max((wake - datetime.now(UTC)).total_seconds(), 0)):
            break
        now = datetime.now(UTC)
        if now >= due:
            due = next_run(now, at, tz)
            attempt(settings)
        elif overdue(settings, now):
            attempt(settings)
    logger.info("backup scheduler stopped")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypted database backups.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="take one backup now")
    serving = commands.add_parser("serve", help="take one every night")
    serving.add_argument("--at", type=time.fromisoformat, default=time(3), help="HH:MM, local")
    commands.add_parser("list", help="the backups in the bucket, newest first")
    fetch = commands.add_parser("fetch", help="download one backup, still encrypted")
    fetch.add_argument("key", help="its object key, or `latest`")
    fetch.add_argument("path", type=Path)
    commands.add_parser("status", help="when the last backup succeeded")
    args = parser.parse_args(argv)

    settings = BackupSettings()
    configure_logging(settings.log_level)

    match args.command:
        case "run":
            init_sentry(settings)
            return 0 if attempt(settings) else 1
        case "serve":
            init_sentry(settings)
            stop = threading.Event()
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, lambda *_: stop.set())
            serve(settings, args.at, stop)
            return 0
        case "list":
            for key, size in backups(client(settings), settings):
                print(f"{key}\t{size}")
            return 0
        case "fetch":
            s3 = client(settings)
            key = args.key
            if key == "latest":
                found = backups(s3, settings)
                if not found:
                    raise SystemExit(f"no backups under {settings.prefix}")
                key = found[0][0]
            if taken_at(key, settings.prefix) is None:
                raise SystemExit(f"{key}: not a backup under {settings.prefix}")
            s3.download_file(settings.backup_s3_bucket, key, str(args.path))
            print(key)
            return 0
        case "status":
            last = last_success(settings)
            print(last.isoformat() if last else "never")
            return 0 if last and datetime.now(UTC) - last <= STALE_AFTER else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
