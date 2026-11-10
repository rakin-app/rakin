"""Nightly backups (`app.backup`): retention, the schedule, the dump pipeline, failures.

The real `pg_dump` and `age` run in `deploy/test-hosted.sh`, which backs up a hosted
stack and restores it with `deploy/restore.sh`. Here they are stand-ins on `PATH`, and
the bucket is the S3 test server when there is one.
"""

import logging
import os
import stat
import threading
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import sentry_sdk

from app import backup
from app.backup import BackupSettings, expired, next_run, object_key, taken_at
from app.integrations.blobstore import s3_client
from tests.conftest import Captured, make_settings

PREFIX = "rakin/staging/"
SANTIAGO = ZoneInfo("America/Santiago")
RECIPIENT = "age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p"


def at(day: str, hour: int = 6) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC)


def nightly(start: str, days: int) -> list[str]:
    first = at(start)
    return [object_key(PREFIX, first + timedelta(days=n)) for n in range(days)]


def make_backup_settings(tmp_path: Path, **overrides: object) -> BackupSettings:
    values: dict[str, object] = {
        "environment": "test",
        "backup_env": "staging",
        "backup_age_recipient": RECIPIENT,
        "backup_s3_endpoint_url": "http://s3.invalid",
        "backup_s3_region": "garage",
        "backup_s3_bucket": "rakin",
        "backup_s3_access_key_id": "key",
        "backup_s3_secret_access_key": "secret",
        "backup_state_dir": tmp_path / "state",
    }
    return BackupSettings(**{**values, **overrides})  # type: ignore[arg-type]


def test_keys_carry_the_utc_time_they_were_taken() -> None:
    taken = datetime(2026, 11, 10, 3, 0, 5, tzinfo=SANTIAGO)

    key = object_key(PREFIX, taken)

    assert key == "rakin/staging/20261110T060005Z.dump.age"
    assert taken_at(key, PREFIX) == taken


@pytest.mark.parametrize(
    "key",
    [
        "rakin/production/20261110T060005Z.dump.age",
        "rakin/staging/20261110T060005Z.dump",
        "rakin/staging/notes.txt",
        "rakin/staging/sub/20261110T060005Z.dump.age",
    ],
)
def test_anything_else_in_the_bucket_is_not_a_backup(key: str) -> None:
    assert taken_at(key, PREFIX) is None


def test_retention_keeps_14_days_and_8_sundays() -> None:
    # 120 nights, Sunday 2026-06-07 to Sunday 2026-10-04.
    keys = nightly("2026-06-07", 120)

    kept = {str(taken_at(k, PREFIX)).split()[0] for k in set(keys) - expired(keys, PREFIX)}

    daily = {f"2026-09-{n}" for n in range(21, 31)} | {f"2026-10-0{n}" for n in range(1, 5)}
    sundays = {
        *("2026-08-16", "2026-08-23", "2026-08-30"),
        *("2026-09-06", "2026-09-13", "2026-09-20", "2026-09-27", "2026-10-04"),
    }
    assert kept == daily | sundays


def test_retention_keeps_the_newest_of_a_day_with_two() -> None:
    keys = [object_key(PREFIX, at("2026-11-10", 6)), object_key(PREFIX, at("2026-11-10", 15))]

    assert expired(keys, PREFIX) == {keys[0]}


def test_retention_counts_backups_not_days_since_today() -> None:
    # The job stopped months ago: its last dumps stay until new ones replace them.
    keys = nightly("2025-01-01", 10)

    assert expired(keys, PREFIX) == set()


def test_retention_never_deletes_what_is_not_a_backup() -> None:
    keys = [*nightly("2026-01-01", 40), "rakin/staging/README", "rakin/production/x.dump.age"]

    gone = expired(keys, PREFIX)

    assert "rakin/staging/README" not in gone
    assert "rakin/production/x.dump.age" not in gone
    # 2026-01-01 to 02-09: the Sundays before the last 14 days are 01-04 to 01-25.
    assert len(gone) == 40 - 14 - 4


def test_the_next_run_is_the_next_3am_in_santiago() -> None:
    three = time(3)
    before = datetime(2026, 11, 10, 2, 59, tzinfo=SANTIAGO)
    after = datetime(2026, 11, 10, 3, 0, tzinfo=SANTIAGO)

    assert next_run(before, three, SANTIAGO) == datetime(2026, 11, 10, 3, tzinfo=SANTIAGO)
    assert next_run(after, three, SANTIAGO) == datetime(2026, 11, 11, 3, tzinfo=SANTIAGO)
    # The host's clock is UTC; 03:00 in Santiago is 06:00 UTC in its summer time.
    utc = datetime(2026, 11, 10, 5, 0, tzinfo=UTC)
    assert next_run(utc, three, SANTIAGO).astimezone(UTC) == datetime(2026, 11, 10, 6, tzinfo=UTC)


def test_settings_refuse_a_key_that_is_not_an_age_public_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="backup_age_recipient"):
        make_backup_settings(tmp_path, backup_age_recipient="AGE-SECRET-KEY-1ABC")


def test_settings_do_not_need_the_apis(tmp_path: Path) -> None:
    # The `backup` container gets only its own variables; a production ENVIRONMENT
    # without SECRET_KEY must not stop it.
    settings = make_backup_settings(tmp_path, environment="production")

    assert settings.prefix == PREFIX


def fake_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dump: str, age: str) -> None:
    """`pg_dump` and `age` on `PATH` as shell scripts."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("pg_dump", dump), ("age", age)):
        script = bin_dir / name
        script.write_text(f"#!/bin/sh\n{body}\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_the_dump_is_piped_through_age_to_the_recipient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_tools(
        tmp_path,
        monkeypatch,
        dump='echo "dump $*"',
        age='echo "age $*"; sed "s/^/sealed:/"',
    )
    out = tmp_path / "out.age"

    backup.dump_encrypted(out, RECIPIENT)

    assert out.read_text() == (
        f"age --encrypt --recipient {RECIPIENT}\nsealed:dump --format=custom\n"
    )


@pytest.mark.parametrize(
    ("dump", "age", "error"),
    [("exit 3", "cat >/dev/null", "pg_dump exited with 3"), ("echo x", "exit 1", "age exited")],
)
def test_a_failing_tool_fails_the_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dump: str, age: str, error: str
) -> None:
    fake_tools(tmp_path, monkeypatch, dump=dump, age=age)

    with pytest.raises(backup.BackupError, match=error):
        backup.dump_encrypted(tmp_path / "out.age", RECIPIENT)


def test_a_failed_backup_is_logged_as_an_error_and_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # ERROR records are what Sentry's logging integration reports.
    fake_tools(tmp_path, monkeypatch, dump="exit 1", age="cat >/dev/null")
    settings = make_backup_settings(tmp_path)
    monkeypatch.setattr(backup, "BackupSettings", lambda: settings)
    monkeypatch.setattr(backup, "configure_logging", lambda level: None)
    started: list[str] = []
    monkeypatch.setattr(backup, "init_sentry", lambda s: started.append(s.sentry_dsn))

    with caplog.at_level(logging.INFO):
        status = backup.main(["run"])

    assert status == 1
    assert started == [""]
    [failure] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert failure.getMessage() == "backup failed"
    assert failure.exc_info is not None
    assert not (settings.backup_state_dir / "last_success").exists()


def test_serve_backs_up_at_once_when_the_last_success_is_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_backup_settings(tmp_path)
    settings.backup_state_dir.mkdir()
    (settings.backup_state_dir / "last_success").write_text(
        f"{(datetime.now(UTC) - timedelta(days=2)).isoformat()} k\n"
    )
    runs: list[BackupSettings] = []
    stop = threading.Event()

    def attempt(s: BackupSettings) -> bool:
        runs.append(s)
        stop.set()
        return True

    monkeypatch.setattr(backup, "attempt", attempt)

    backup.serve(settings, time(3), stop)

    assert runs == [settings]


def test_serve_waits_for_the_night_after_a_recent_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_backup_settings(tmp_path)
    settings.backup_state_dir.mkdir()
    (settings.backup_state_dir / "last_success").write_text(f"{datetime.now(UTC).isoformat()} k\n")
    runs: list[BackupSettings] = []

    def attempt(s: BackupSettings) -> bool:
        runs.append(s)
        return True

    monkeypatch.setattr(backup, "attempt", attempt)
    stop = threading.Event()
    stop.set()

    backup.serve(settings, time(3), stop)

    assert runs == []


def test_status_is_non_zero_without_a_recent_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_backup_settings(tmp_path)
    monkeypatch.setattr(backup, "BackupSettings", lambda: settings)
    monkeypatch.setattr(backup, "configure_logging", lambda level: None)

    assert backup.main(["status"]) == 1
    assert capsys.readouterr().out == "never\n"

    settings.backup_state_dir.mkdir()
    (settings.backup_state_dir / "last_success").write_text(
        f"{(datetime.now(UTC) - timedelta(hours=27)).isoformat()} k\n"
    )
    assert backup.main(["status"]) == 1

    (settings.backup_state_dir / "last_success").write_text(f"{datetime.now(UTC).isoformat()} k\n")
    assert backup.main(["status"]) == 0


@pytest.fixture
def s3_backup_settings(tmp_path: Path) -> BackupSettings:
    endpoint = os.environ.get("TEST_S3_ENDPOINT_URL")
    if not endpoint:
        if os.environ.get("REQUIRE_S3"):
            pytest.fail("REQUIRE_S3 is set but TEST_S3_ENDPOINT_URL is not")
        pytest.skip("TEST_S3_ENDPOINT_URL not set")
    # The app's test bucket and key, under a folder of this test's own.
    app = make_settings(s3_endpoint_url=endpoint)
    return make_backup_settings(
        tmp_path,
        backup_env=f"test-{uuid.uuid4()}",
        backup_s3_endpoint_url=endpoint,
        backup_s3_region=app.s3_region,
        backup_s3_bucket=app.s3_bucket,
        backup_s3_access_key_id=app.s3_access_key_id,
        backup_s3_secret_access_key=app.s3_secret_access_key,
    )


@pytest.mark.s3
def test_a_backup_is_uploaded_and_retention_prunes_the_bucket(
    s3_backup_settings: BackupSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = s3_backup_settings
    fake_tools(tmp_path, monkeypatch, dump="echo dump", age="sed s/^/sealed:/")
    s3 = s3_client(
        settings.backup_s3_endpoint_url,
        settings.backup_s3_region,
        settings.backup_s3_access_key_id,
        settings.backup_s3_secret_access_key,
    )
    old = nightly("2026-09-01", 20)
    for key in [*old, f"{settings.prefix}README"]:
        s3.put_object(Bucket=settings.backup_s3_bucket, Key=key.replace(PREFIX, settings.prefix))

    now = at("2026-09-21", 7)
    key = backup.run_once(settings, now)

    body = s3.get_object(Bucket=settings.backup_s3_bucket, Key=key)["Body"].read()
    assert body == b"sealed:dump\n"
    left = [k for k, _ in backup.backups(s3, settings)]
    assert left[0] == key
    # 14 days (the new one and 13 of the old), and the Sunday before them, 09-06.
    assert len(left) == 14 + 1
    readme = s3.list_objects_v2(Bucket=settings.backup_s3_bucket, Prefix=f"{settings.prefix}R")
    assert readme["KeyCount"] == 1
    assert (settings.backup_state_dir / "last_success").read_text() == f"{now.isoformat()} {key}\n"


class FailingListS3:
    """Takes the upload, then fails to list the bucket, as a flaky R2 might."""

    def __init__(self) -> None:
        self.uploaded: list[str] = []

    def upload_file(self, path: str, bucket: str, key: str) -> None:
        self.uploaded.append(key)

    def get_paginator(self, name: str) -> object:
        raise ConnectionError("R2 went away")


def test_a_failed_prune_does_not_fail_an_uploaded_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sentry: Captured,
) -> None:
    fake_tools(tmp_path, monkeypatch, dump="echo dump", age="cat")
    settings = make_backup_settings(tmp_path)
    s3 = FailingListS3()
    monkeypatch.setattr(backup, "client", lambda s: s3)
    with caplog.at_level(logging.INFO):
        assert backup.attempt(settings) is True

    [key] = s3.uploaded
    assert taken_at(key, PREFIX) is not None
    assert (settings.backup_state_dir / "last_success").exists()
    [warning] = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warning.levelno == logging.WARNING
    assert warning.exc_info is not None
    sentry_sdk.flush()
    [event] = [e for env in sentry.envelopes if (e := env.get_event()) is not None]
    assert event["level"] == "warning"
    [exception] = event["exception"]["values"]
    assert exception["type"] == "ConnectionError"


def test_serve_retries_on_the_next_tick_after_a_failed_night(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_backup_settings(tmp_path)
    settings.backup_state_dir.mkdir()
    (settings.backup_state_dir / "last_success").write_text(
        f"{(datetime.now(UTC) - timedelta(hours=30)).isoformat()} k\n"
    )
    outcomes = iter([False, False, True])
    runs: list[bool] = []
    stop = threading.Event()

    def attempt(s: BackupSettings) -> bool:
        ok = next(outcomes)
        runs.append(ok)
        if ok:
            (s.backup_state_dir / "last_success").write_text(f"{datetime.now(UTC).isoformat()} k\n")
            # One more tick, which must not back up again: the success is recent.
            threading.Timer(0.05, stop.set).start()
        return ok

    monkeypatch.setattr(backup, "attempt", attempt)

    backup.serve(settings, time(3), stop, tick=timedelta(milliseconds=10))

    assert runs == [False, False, True]
