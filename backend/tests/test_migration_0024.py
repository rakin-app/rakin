"""Migration 0024: belt colours filled in on schemes stored from the BJJ preset (#135).

The backfill on its own first, then against real Postgres, where the gyms' RLS is
FORCEd on the owner that runs it.
"""

import copy
import importlib.util
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from alembic import command
from app.schemas.grading import PRESETS
from tests.conftest import require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, throwaway_database

_spec = importlib.util.spec_from_file_location(
    "migration_0024",
    Path(__file__).parents[1] / "alembic" / "versions" / "0024_belt_colours.py",
)
assert _spec and _spec.loader
m0024 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m0024)

PRESET = next(p.scheme.model_dump(mode="json") for p in PRESETS if p.key == "bjj")
MUAY_THAI = next(p.scheme.model_dump(mode="json") for p in PRESETS if p.key == "muay-thai")


def uncoloured(scheme: dict[str, Any]) -> dict[str, Any]:
    """`scheme` as stored before ranks had colours."""
    old = copy.deepcopy(scheme)
    for rank in (*old["ranks"], *old["kids_ladder"]):
        rank.pop("colors", None)
    return old


def colours(scheme: dict[str, Any]) -> list[list[str] | None]:
    return [r.get("colors") for r in (*scheme["ranks"], *scheme["kids_ladder"])]


# --- the backfill, no database ------------------------------------------------------


def test_the_colours_are_the_presets() -> None:
    # Copied, not imported: they must still agree with the preset as it stands.
    scheme = uncoloured(PRESET)
    assert m0024.backfill(scheme)
    assert scheme == PRESET


def test_labels_match_ignoring_case_accents_and_spaces() -> None:
    scheme = uncoloured(PRESET)
    for rank, label in zip(scheme["ranks"], ["BLANCA", " azul", "Morada ", "Cafe", "negra"]):
        rank["label"] = label
    scheme["kids_ladder"][0]["label"] = "gris  Y  Blanca"
    m0024.backfill(scheme)
    assert colours(scheme) == colours(PRESET)


def test_only_ranks_without_colours_and_with_the_presets_names_are_coloured() -> None:
    scheme = uncoloured(PRESET)
    scheme["ranks"][1]["colors"] = ["#000080"]  # the gym's own blue
    scheme["ranks"].insert(1, {"key": "white-gold", "label": "Blanca y dorada", "sub_ranks": []})
    m0024.backfill(scheme)
    assert scheme["ranks"][1].get("colors") is None
    assert scheme["ranks"][2]["colors"] == ["#000080"]
    assert scheme["ranks"][0]["colors"] == PRESET["ranks"][0]["colors"]


@pytest.mark.parametrize(
    "scheme",
    [
        uncoloured(MUAY_THAI),  # shares Azul, Verde and Café, not the belts
        {"ranks": [{"key": "blue", "label": "Azul", "sub_ranks": []}], "kids_ladder": []},
        {"ranks": [], "kids_ladder": []},
        {"ranks": "rotas"},
    ],
    ids=["prajioud", "one-belt", "none", "malformed"],
)
def test_a_scheme_of_other_ranks_is_left_alone(scheme: dict[str, Any]) -> None:
    before = copy.deepcopy(scheme)
    assert not m0024.backfill(scheme)
    assert scheme == before


# --- against real Postgres ----------------------------------------------------------


@pytest.fixture
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database, "0023")
        yield database


def store(db: Database, slug: str, grading: dict[str, Any] | None) -> uuid.UUID:
    gym = seed_gym(db, slug)
    if grading is not None:
        settings = {"grace_days": 5, "grading": grading}
        run(
            db.admin_url,
            lambda c: c.execute(
                "UPDATE gym SET settings = $1::jsonb WHERE id = $2", json.dumps(settings), gym
            ),
        )
    return gym


def settings(db: Database, gym: uuid.UUID) -> dict[str, Any]:
    row = run(db.admin_url, lambda c: c.fetchval("SELECT settings FROM gym WHERE id = $1", gym))
    return json.loads(row)  # type: ignore[no-any-return]


@pytest.mark.postgres
def test_every_gym_is_backfilled_and_the_downgrade_takes_it_back(db: Database) -> None:
    bjj = store(db, "academia-sur", uncoloured(PRESET))
    other = store(db, "academia-norte", uncoloured(PRESET))
    prajioud = store(db, "camp-thai", uncoloured(MUAY_THAI))
    bare = store(db, "sin-grados", None)

    migrate(db, "0024")

    for gym in (bjj, other):
        stored = settings(db, gym)
        assert stored["grading"] == PRESET
        assert stored["grace_days"] == 5  # the rest of the settings untouched
    assert settings(db, prajioud)["grading"] == uncoloured(MUAY_THAI)
    assert "grading" not in settings(db, bare)
    # FORCE is back on the gym table.
    forced = run(
        db.admin_url,
        lambda c: c.fetchval("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'gym'"),
    )
    assert forced is True

    command.downgrade(db.alembic(), "0023")
    assert settings(db, bjj)["grading"] == uncoloured(PRESET)
    assert run(
        db.admin_url,
        lambda c: c.fetchval("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'gym'"),
    )
