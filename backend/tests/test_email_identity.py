"""Sign-in by email reaches a gym only where that gym's own record holds the email (#146).

Identity is global by RUT (migration 0036), so two gyms can know one person, each with
its own record of their email. Whatever gym B writes on its record must sign nobody in to gym A: not
the session sign-in starts (one gym), not the gyms a person in several picks from
(#16), and not a session that names gym A some other way. Each test writes the email
the way the API lets a gym write one: adding or editing a person, inviting staff,
importing the sheet, and on a person gym A has only as a guardian.

Writes go through the API as gym B's owner (`tests.auth.FakeAuth`); sign-in is the real
magic-link flow, with a mailer that keeps what it is given.
"""

import dataclasses
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import asyncpg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from alembic import command
from app.auth import MailSender
from app.integrations.mailer import Email
from app.magiclink import COOKIE_NAME
from app.magiclink.tokens import hash_token
from app.main import create_app
from app.notices import Notices
from tests.auth import FakeAuth, as_gym
from tests.conftest import require_test_database_url
from tests.ids import random_rut
from tests.pg import Database, in_gym, migrate, run, seed_gym, throwaway_database
from tests.test_tenancy import router as tenant_routes

pytestmark = pytest.mark.postgres

BASE_URL = "https://testserver"


@dataclass
class Outbox:
    sent: list[Email] = field(default_factory=list)

    async def send(self, email: Email) -> None:
        self.sent.append(email)

    def links_to(self, address: str) -> list[str]:
        """The sign-in links mailed to `address`, oldest first."""
        return [
            word
            for email in self.sent
            if email.to.lower() == address.strip().lower()
            for word in email.text.split()
            if word.startswith(f"{BASE_URL}/api/auth/callback")
        ]


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@dataclass
class Gyms:
    a: uuid.UUID  # the victim's gym
    b: uuid.UUID  # the gym that writes an email on them


@pytest.fixture
def gyms(db: Database) -> Gyms:
    return Gyms(
        seed_gym(db, f"gym-a-{uuid.uuid4().hex[:6]}"), seed_gym(db, f"gym-b-{uuid.uuid4().hex[:6]}")
    )


@dataclass
class Harness:
    client: TestClient
    outbox: Outbox
    db: Database

    def write(self, method: str, path: str, gym: uuid.UUID, **body: Any) -> Any:
        """As `gym`'s owner, before anyone signs in on this client."""
        assert COOKIE_NAME not in self.client.cookies
        response = self.client.request(method, path, json=body, headers=as_gym(gym))
        assert response.status_code in (200, 201), response.text
        return response.json()

    def sign_in(self, address: str) -> str | None:
        """Request a link for `address` and spend the latest one; the session token, or
        None when no link went."""
        assert self.client.post("/api/auth/link", json={"email": address}).status_code == 202
        links = self.outbox.links_to(address)
        if not links:
            return None
        token = parse_qs(urlsplit(links[-1]).query)["token"][0]
        response = self.client.post("/api/auth/callback", data={"token": token})
        assert response.status_code == 303
        return str(self.client.cookies[COOKIE_NAME])

    def gym_of_session(self) -> str | None:
        response = self.client.get("/test/setting")
        return None if response.status_code == 401 else str(response.json()["gym"])


@pytest.fixture
def harness(db: Database) -> Iterator[Harness]:
    app: FastAPI = create_app(db.settings.model_copy(update={"public_base_url": BASE_URL}))
    app.include_router(tenant_routes)
    app.add_middleware(FakeAuth)
    outbox = Outbox()
    app.state.integrations = dataclasses.replace(app.state.integrations, mailer=outbox)
    app.state.magic_links.sender = MailSender(
        Notices(
            outbox,
            lambda: app.state.sessionmaker,
            base_url=BASE_URL,
            secret_key=db.settings.secret_key,
        )
    )
    with TestClient(app, base_url=BASE_URL, follow_redirects=False) as client:
        yield Harness(client, outbox, db)


def address() -> str:
    return f"{uuid.uuid4().hex[:10]}@example.cl"


def member_of(db: Database, gym: uuid.UUID, person: uuid.UUID) -> None:
    """Give `person` a membership in `gym`, so the gym's record of them signs in."""

    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute(
            "INSERT INTO membership (gym_id, person_id, plan_id, status)"
            " SELECT gym_id, $1, id, 'active' FROM plan WHERE gym_id = $2 LIMIT 1",
            person,
            gym,
        )

    run(db.admin_url, query)


def victim(h: Harness, gyms: Gyms, *, email: str | None = None) -> tuple[uuid.UUID, str]:
    """A member of gym A, with gym A's record of their email; their id and RUT."""
    rut = random_rut()
    body = {"rut": rut, "name": "Víctima", "email": email or address()}
    person = uuid.UUID(h.write("POST", "/api/people", gyms.a, **body)["id"])
    member_of(h.db, gyms.a, person)
    return person, rut


def gyms_of(db: Database, person: uuid.UUID, email: str) -> set[uuid.UUID]:
    """The gyms a sign-in with `email` reaches for `person`: what the picker offers."""
    rows = run(db.api_url, in_gym(None, "SELECT auth_gyms_of($1, $2)", person, email))
    return {r[0] for r in rows}


def assert_reaches_only_b(h: Harness, gyms: Gyms, person: uuid.UUID, attacker: str) -> None:
    # Without the picker: the session starts in gym B, the attacker's own.
    assert h.sign_in(attacker) is not None
    assert h.gym_of_session() == str(gyms.b)
    # With it: gym A is not among the gyms to pick.
    assert gyms_of(h.db, person, attacker) == {gyms.b}


# --- every write path ------------------------------------------------------------------


def test_adding_a_person_with_an_email(harness: Harness, gyms: Gyms) -> None:
    person, rut = victim(harness, gyms)
    attacker = address()

    added = harness.write("POST", "/api/people", gyms.b, rut=rut, name="X", email=attacker)
    assert uuid.UUID(added["id"]) == person
    member_of(harness.db, gyms.b, person)

    assert_reaches_only_b(harness, gyms, person, attacker)


def test_editing_a_persons_email(harness: Harness, gyms: Gyms) -> None:
    person, rut = victim(harness, gyms)
    attacker = address()
    harness.write("POST", "/api/people", gyms.b, rut=rut, name="X")
    member_of(harness.db, gyms.b, person)

    harness.write("PATCH", f"/api/people/{person}", gyms.b, email=attacker)

    assert_reaches_only_b(harness, gyms, person, attacker)


def test_inviting_them_as_staff(harness: Harness, gyms: Gyms) -> None:
    person, rut = victim(harness, gyms)
    attacker = address()

    invited = harness.write(
        "POST", "/api/staff", gyms.b, rut=rut, name="X", email=attacker, role="admin"
    )
    assert uuid.UUID(invited["person_id"]) == person
    # The invite's email is gym B's to write: it signs in to gym B alone.
    assert invited["email"] == attacker
    harness.outbox.sent.clear()

    assert_reaches_only_b(harness, gyms, person, attacker)


def test_importing_them_from_the_sheet(harness: Harness, gyms: Gyms) -> None:
    person, rut = victim(harness, gyms)
    attacker = address()

    report = harness.write(
        "POST",
        "/api/import/members",
        gyms.b,
        rows=[{"number": 2, "cells": ["X", rut, attacker]}],
        mapping={"name": 0, "rut": 1, "email": 2},
        plans={},
        dry_run=False,
    )
    assert report["rows"][0]["person"] == "created"
    member_of(harness.db, gyms.b, person)

    assert_reaches_only_b(harness, gyms, person, attacker)


def test_a_person_gym_a_has_only_as_a_guardian(harness: Harness, gyms: Gyms) -> None:
    rut = random_rut()
    guardian = harness.write("POST", "/api/people", gyms.a, rut=rut, name="Mamá", email=address())
    person = uuid.UUID(guardian["id"])
    harness.write("POST", f"/api/people/{person}/dependents", gyms.a, name="Hijo")
    attacker = address()

    harness.write("POST", "/api/people", gyms.b, rut=rut, name="X", email=attacker)
    member_of(harness.db, gyms.b, person)

    assert_reaches_only_b(harness, gyms, person, attacker)


def test_a_gym_b_email_nobody_else_belongs_to_reaches_no_gym(harness: Harness, gyms: Gyms) -> None:
    """Gym B writes the email but gives them nothing there: no link goes at all."""
    person, rut = victim(harness, gyms)
    attacker = address()

    harness.write("POST", "/api/people", gyms.b, rut=rut, name="X", email=attacker)

    assert harness.sign_in(attacker) is None
    assert gyms_of(harness.db, person, attacker) == set()


# --- the rule itself -------------------------------------------------------------------


def test_the_victims_own_email_still_signs_them_in_to_gym_a(harness: Harness, gyms: Gyms) -> None:
    theirs = address()
    person, rut = victim(harness, gyms, email=theirs)
    harness.write("POST", "/api/people", gyms.b, rut=rut, name="X", email=address())
    member_of(harness.db, gyms.b, person)

    assert harness.sign_in(theirs) is not None
    assert harness.gym_of_session() == str(gyms.a)
    assert gyms_of(harness.db, person, theirs) == {gyms.a}


def test_an_email_both_gyms_hold_reaches_both_and_picks_neither_yet(
    harness: Harness, gyms: Gyms
) -> None:
    theirs = address()
    person, rut = victim(harness, gyms, email=theirs)
    harness.write("POST", "/api/people", gyms.b, rut=rut, name="X", email=theirs.upper())
    member_of(harness.db, gyms.b, person)

    assert harness.sign_in(theirs) is not None
    assert harness.gym_of_session() is None
    assert gyms_of(harness.db, person, f" {theirs.upper()} ") == {gyms.a, gyms.b}


def session_in(db: Database, token: str, gym: uuid.UUID) -> None:
    """Point a session at `gym`, as a picker would, straight in the table."""
    run(
        db.admin_url,
        lambda c: c.execute(
            "UPDATE auth_session SET gym_id = $1 WHERE token_hash = $2", gym, hash_token(token)
        ),
    )


def test_a_session_pointed_at_gym_a_is_not_live_there(harness: Harness, gyms: Gyms) -> None:
    """However a session comes to name gym A, its email must be gym A's for it to work."""
    person, rut = victim(harness, gyms)
    attacker = address()
    harness.write("POST", "/api/people", gyms.b, rut=rut, name="X", email=attacker)
    member_of(harness.db, gyms.b, person)
    token = harness.sign_in(attacker)
    assert token is not None

    session_in(harness.db, token, gyms.a)

    assert harness.gym_of_session() is None
    lookup = "SELECT person_id FROM auth_live_session($1, now())"
    assert run(harness.db.api_url, in_gym(None, lookup, hash_token(token))) == []


def test_a_gym_that_changes_the_email_ends_the_sessions_signed_in_with_the_old_one(
    harness: Harness, gyms: Gyms
) -> None:
    theirs = address()
    person, _ = victim(harness, gyms, email=theirs)
    assert harness.sign_in(theirs) is not None
    assert harness.gym_of_session() == str(gyms.a)

    run(
        harness.db.admin_url,
        lambda c: c.execute(
            "UPDATE gym_person SET email = $1 WHERE gym_id = $2 AND person_id = $3",
            address(),
            gyms.a,
            person,
        ),
    )

    assert harness.gym_of_session() is None


def test_the_link_and_the_session_record_the_address_signed_in_with(
    harness: Harness, gyms: Gyms
) -> None:
    theirs = address()
    victim(harness, gyms, email=theirs)
    token = harness.sign_in(f" {theirs.upper()} ")
    assert token is not None

    [row] = run(
        harness.db.admin_url,
        lambda c: c.fetch(
            "SELECT s.email AS session, l.email AS link FROM auth_session s"
            " JOIN auth_link l ON l.person_id = s.person_id WHERE s.token_hash = $1",
            hash_token(token),
        ),
    )
    # The address the link went to: the gym's record of it, not what was typed.
    assert (row["session"].lower(), row["link"].lower()) == (theirs, theirs)


# --- the migration ---------------------------------------------------------------------


def test_the_migration_ends_earlier_links_and_sessions_and_downgrades() -> None:
    with throwaway_database(require_test_database_url()) as scratch:
        migrate(scratch, "0028")
        gym = seed_gym(scratch, "antes")
        person, link, session = uuid.uuid4(), uuid.uuid4().bytes * 2, uuid.uuid4().bytes * 2

        async def before(conn: asyncpg.Connection) -> None:
            await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
            await conn.execute(
                "INSERT INTO auth_link (token_hash, person_id, expires_at)"
                " VALUES ($1, $2, now() + interval '1 hour')",
                link,
                person,
            )
            await conn.execute(
                "INSERT INTO auth_session (token_hash, person_id, gym_id, expires_at)"
                " VALUES ($1, $2, $3, now() + interval '1 day')",
                session,
                person,
                gym,
            )

        run(scratch.admin_url, before)
        migrate(scratch)

        ended = (
            "SELECT (SELECT used_at IS NOT NULL FROM auth_link WHERE token_hash = $1),"
            " (SELECT ended_at IS NOT NULL FROM auth_session WHERE token_hash = $2)"
        )
        assert tuple(run(scratch.admin_url, lambda c: c.fetchrow(ended, link, session))) == (
            True,
            True,
        )

        functions = (
            "SELECT array_agg(p ORDER BY p) FROM"
            " (SELECT oid::regprocedure::text AS p FROM pg_proc"
            " WHERE proname IN ('auth_gyms_of', 'staff_invite_email_ok')) f"
        )
        command.downgrade(scratch.alembic(), "0028")
        assert run(scratch.admin_url, lambda c: c.fetchval(functions)) == [
            "auth_gyms_of(uuid)",
            "staff_invite_email_ok(uuid,text)",
        ]
        migrate(scratch)
        assert run(scratch.admin_url, lambda c: c.fetchval(functions)) == [
            "auth_gyms_of(uuid,text)"
        ]
