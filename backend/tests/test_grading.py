"""Grading scheme: the presets, the input rules, and the API that stores it in `gym.settings`.

Read access per role is covered with the other endpoint groups in `tests/test_roles.py`.
"""

import copy
import json
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.domain import grading
from app.main import create_app
from app.schemas.grading import PRESETS, GradingScheme
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.ids import unique_slug
from tests.pg import Database, make_staff, migrate, run, seed_gym, throwaway_database

APP = Path(__file__).parent.parent / "app"
BJJ = next(p.scheme.model_dump() for p in PRESETS if p.key == "bjj")
NONE: dict[str, Any] = {"ranks": [], "kids_ladder": [], "goal_metric": None}

# --- presets and input rules, no database -------------------------------------------


def test_the_presets_are_the_spec_table() -> None:
    by_key = {p.key: p.scheme for p in PRESETS}
    assert list(by_key) == [
        "bjj",
        "judo",
        "karate",
        "karate-shotokan",
        "karate-kyokushin",
        "karate-goju-ryu",
        "taekwondo",
        "kenpo",
        "aikido",
        "muay-thai",
        "levels",
        "none",
    ]

    bjj = by_key["bjj"]
    assert [r.key for r in bjj.ranks] == ["white", "blue", "purple", "brown", "black"]
    assert all([s.key for s in r.sub_ranks] == ["0", "1", "2", "3", "4"] for r in bjj.ranks)
    assert [r.key for r in bjj.kids_ladder][:3] == ["grey-white", "grey", "grey-black"]
    assert len(bjj.kids_ladder) == 12
    # Every BJJ belt is coloured; two-tone kids' belts carry their stripe second.
    assert all(len(r.colors) == 1 for r in bjj.ranks)
    by_rank = {r.key: r.colors for r in bjj.kids_ladder}
    assert by_rank["grey-white"] == [by_rank["grey"][0], bjj.ranks[0].colors[0]]
    assert by_rank["green-black"] == [by_rank["green"][0], bjj.ranks[-1].colors[0]]
    assert bjj.goal_metric == "classes_since_promotion"

    karate = by_key["karate"]
    keys = [r.key for r in karate.ranks]
    assert keys[0] == "kyu-10" and keys[9:11] == ["kyu-1", "dan-1"] and keys[-1] == "dan-10"
    assert all(not r.sub_ranks for r in karate.ranks)
    # Kyu and dan are belts (#353): white first, black from 1.º dan, red at 10.º.
    assert all(r.colors for r in karate.ranks) and karate.belts
    by_karate = {r.key: r.colors for r in karate.ranks}
    assert by_karate["kyu-10"] == bjj.ranks[0].colors
    assert by_karate["dan-1"] == bjj.ranks[-1].colors
    assert len(by_karate["dan-6"]) == 2 and by_karate["dan-10"] == by_karate["dan-6"][:1]
    assert karate.kids_ladder == []  # kids climb the same ladder
    assert karate.goal_metric == "time_in_rank"

    muay_thai = by_key["muay-thai"]
    assert muay_thai.ranks and muay_thai.kids_ladder == []
    assert muay_thai.goal_metric is None
    # Prajioud are arm bands (#353): each its colour, white first and black last.
    assert all(len(r.colors) == 1 for r in muay_thai.ranks) and muay_thai.belts
    assert muay_thai.ranks[0].colors == bjj.ranks[0].colors
    assert muay_thai.ranks[-1].colors == bjj.ranks[-1].colors

    # Levels (#353): an empty list to fill, read as levels since no rank has colours.
    assert by_key["levels"].model_dump() == NONE
    assert bjj.belts and not by_key["levels"].belts

    assert by_key["none"].model_dump() == NONE


def _belts(key: str) -> list[tuple[str, list[str]]]:
    """A preset's ranks, by key, and the names of their colours."""
    names = {colour: name for name, colour in grading._BELT.items()}
    scheme = next(p.scheme for p in PRESETS if p.key == key)
    return [(r.key, [names[c] for c in r.colors]) for r in scheme.ranks]


def test_each_art_has_its_own_ladder() -> None:
    # Judo (#411): six kyu, white to brown, then the dan, no longer karate's ten kyu.
    judo = dict(_belts("judo"))
    assert list(judo)[:7] == ["kyu-6", "kyu-5", "kyu-4", "kyu-3", "kyu-2", "kyu-1", "dan-1"]
    assert [judo[f"kyu-{n}"][0] for n in range(6, 0, -1)] == [
        "white",
        "yellow",
        "orange",
        "green",
        "blue",
        "brown",
    ]
    assert judo["dan-1"] == ["black"] and judo["dan-6"] == ["red", "white"]
    assert judo["dan-10"] == ["red"]

    # Shotokan, nine kyu to three of brown; black to 10.º dan.
    shotokan = dict(_belts("karate-shotokan"))
    assert next(iter(shotokan)) == "kyu-9"
    assert [shotokan[f"kyu-{n}"] for n in (3, 2, 1)] == [["brown"]] * 3
    assert all(shotokan[f"dan-{n}"] == ["black"] for n in range(1, 11))

    # Kyokushin: mukyu, then each colour twice, the second with the next one's stripe.
    kyokushin = _belts("karate-kyokushin")
    assert kyokushin[:4] == [
        ("mukyu", ["white"]),
        ("kyu-10", ["orange"]),
        ("kyu-9", ["orange", "blue"]),
        ("kyu-8", ["blue"]),
    ]
    assert dict(kyokushin)["kyu-1"] == ["brown", "black"]

    # Goju-ryu: ten kyu, white first and brown last, then black.
    goju = dict(_belts("karate-goju-ryu"))
    assert goju["kyu-10"] == ["white"] and goju["kyu-1"] == ["brown"]
    assert goju["dan-1"] == ["black"]

    # Taekwondo, WT: ten gup, the steps between colours tipped with the next, 9 dan.
    taekwondo = _belts("taekwondo")
    assert [k for k, _ in taekwondo][:2] == ["gup-10", "gup-9"]
    assert [c for _, c in taekwondo][:3] == [["white"], ["white", "yellow"], ["yellow"]]
    assert dict(taekwondo)["gup-1"] == ["red", "black"]
    assert [k for k, _ in taekwondo][-1] == "dan-9"
    assert next(p.label for p in PRESETS if p.key == "taekwondo") == "Taekwondo (WT)"

    # American Kenpo: white to green, brown counting down, then black's ten degrees.
    kenpo = _belts("kenpo")
    assert [c[0] for _, c in kenpo][:6] == ["white", "yellow", "orange", "purple", "blue", "green"]
    assert [k for k, _ in kenpo][6:10] == ["brown-3", "brown-2", "brown-1", "black-1"]
    assert len(kenpo) == 19 and kenpo[-1] == ("black-10", ["black"])

    # Aikido, Aikikai: six white kyu, then black.
    aikido = dict(_belts("aikido"))
    assert [aikido[f"kyu-{n}"] for n in range(6, 0, -1)] == [["white"]] * 6
    assert aikido["dan-1"] == ["black"]


def test_the_old_judo_karate_key_is_judo() -> None:
    assert grading.resolve("judo-karate") == "judo"
    assert grading.resolve("bjj") == "bjj"
    assert "judo-karate" not in {p.key for p in PRESETS}


@pytest.mark.parametrize(
    ("key", "belts"),
    [
        *((p.key, True) for p in PRESETS if p.key not in ("levels", "none")),
        ("levels", False),
        ("none", False),
    ],
)
def test_a_preset_reads_as_belts_only_when_its_ranks_have_colours(key: str, belts: bool) -> None:
    # A belt or arm-band sport says "Cinturón"; levels and no grades say "Nivel" (#353).
    scheme = next(p.scheme for p in PRESETS if p.key == key)
    assert scheme.belts is belts
    if belts:
        assert all(r.colors for r in (*scheme.ranks, *scheme.kids_ladder))


def test_a_gym_with_no_scheme_has_none() -> None:
    assert GradingScheme.from_settings({}).model_dump() == NONE


def test_a_preset_is_a_starting_point_and_is_edited_like_any_scheme() -> None:
    scheme = copy.deepcopy(BJJ)
    scheme["ranks"].insert(1, {"key": "white-gold", "label": "Blanca y dorada"})
    scheme["ranks"][0]["sub_ranks"] = scheme["ranks"][0]["sub_ranks"][:3]
    scheme["kids_ladder"] = []
    scheme["goal_metric"] = "time_in_rank"
    edited = GradingScheme.model_validate(scheme)
    assert [r.key for r in edited.ranks][:3] == ["white", "white-gold", "blue"]
    assert edited.ranks[1].sub_ranks == []


def test_a_rank_or_sub_rank_carries_an_optional_target() -> None:
    def targets(s: dict[str, Any]) -> None:
        s["ranks"][0]["target"] = 200
        s["ranks"][0]["sub_ranks"][2]["target"] = 80

    scheme = GradingScheme.model_validate(_with(targets))
    assert scheme.ranks[0].target == 200
    assert [s.target for s in scheme.ranks[0].sub_ranks] == [None, None, 80, None, None]
    assert scheme.ranks[1].target is None
    # Months in rank count the same way.
    judo = next(p.scheme.model_dump() for p in PRESETS if p.key == "judo")
    judo["ranks"][0]["target"] = 6
    assert GradingScheme.model_validate(judo).ranks[0].target == 6


def _with(change: Any) -> dict[str, Any]:
    scheme = copy.deepcopy(BJJ)
    change(scheme)
    return scheme


@pytest.mark.parametrize(
    "scheme",
    [
        {},
        {"ranks": None},
        {**NONE, "goal_metric": "classes_since_promotion"},
        {**NONE, "goal_metric": "stripes"},
        {**NONE, "sport": "bjj"},
        _with(lambda s: s["ranks"].append({"key": "blue", "label": "Azul otra vez"})),
        _with(lambda s: s["kids_ladder"].append({"key": "white", "label": "Blanca"})),
        _with(lambda s: s["ranks"][0]["sub_ranks"].append({"key": "4", "label": "Otra"})),
        _with(lambda s: s["ranks"][0].update(key="Blue")),
        _with(lambda s: s["ranks"][0].update(key="azul marino")),
        _with(lambda s: s["ranks"][0].update(key="-blue")),
        _with(lambda s: s["ranks"][0].update(key="")),
        _with(lambda s: s["ranks"][0].update(label="  ")),
        _with(lambda s: s["ranks"][0].update(color="#fff")),
        _with(lambda s: s["ranks"][0].update(colors=["#fff"])),
        _with(lambda s: s["ranks"][0].update(colors=["blue"])),
        _with(lambda s: s["ranks"][0].update(colors=["#111111", "#222222", "#333333"])),
        _with(lambda s: s["ranks"][0]["sub_ranks"][0].update(key=0)),
        {**NONE, "ranks": [{"key": f"r{n}", "label": "x"} for n in range(61)]},
        _with(lambda s: s["ranks"][0].update(target=0)),
        _with(lambda s: s["ranks"][0].update(target=10_001)),
        _with(lambda s: s["ranks"][0]["sub_ranks"][1].update(target=-3)),
        _with(lambda s: s["ranks"][0].update(target="ochenta")),
        # A target counts the goal metric, so it needs one.
        _with(lambda s: (s["ranks"][0].update(target=80), s.update(goal_metric=None))),
        _with(
            lambda s: (
                s["kids_ladder"][0]["sub_ranks"][0].update(target=8),
                s.update(goal_metric=None),
            )
        ),
    ],
    ids=str,
)
def test_a_scheme_is_refused(scheme: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        GradingScheme.model_validate(scheme)


def test_no_code_outside_the_presets_names_a_sport() -> None:
    # Sport lives in configuration: the presets are data, and nothing branches on them.
    sports = re.compile(
        r"\b(bjj|jiu-?jitsu|judo|karate|taekwondo|kenpo|aikido|muay|thai|boxing|mma)\b", re.I
    )
    allowed = {
        APP / "domain" / "grading.py",
        APP / "domain" / "vocabulary.py",
        APP / "domain" / "practice.py",
    }
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if path not in allowed and sports.search(path.read_text())
    ]
    # The demo gym is a BJJ academy and loads its preset by key.
    assert offenders == [str(Path("seed") / "data.py")]
    assert grading.PRESETS  # the module the check allows


# --- against real Postgres -----------------------------------------------------------

pg = pytest.mark.postgres

URL = "/api/gym/grading-scheme"


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def client(db: Database) -> Iterator[TestClient]:
    app = create_app(make_settings(database_url=db.api_url))
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


def stored(db: Database, gym: uuid.UUID) -> dict[str, Any]:
    row = run(db.admin_url, lambda c: c.fetchval("SELECT settings FROM gym WHERE id = $1", gym))
    return json.loads(row)  # type: ignore[no-any-return]


def staff(db: Database, gym: uuid.UUID, role: str) -> uuid.UUID:
    person = uuid.uuid4()

    async def query(conn: Any) -> None:
        await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", person)
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')", gym, person
        )
        await make_staff(conn, gym, person, role)

    run(db.admin_url, query)
    return person


@pg
def test_a_new_gym_has_no_scheme(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "dojo-sin-grados")
    response = client.get(URL, headers=as_gym(gym))
    assert response.status_code == 200
    assert response.json() == NONE


@pg
def test_the_presets_are_listed(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "dojo-presets")
    response = client.get(f"{URL}/presets", headers=as_gym(gym))
    assert response.status_code == 200
    assert [p["key"] for p in response.json()] == [p.key for p in PRESETS]
    assert "karate-shotokan" in [p["key"] for p in response.json()]
    assert response.json()[0]["scheme"] == BJJ


@pg
@pytest.mark.parametrize("key", [p.key for p in PRESETS if p.scheme.belts])
def test_each_belt_preset_applies_and_reads_back(
    client: TestClient, db: Database, key: str
) -> None:
    gym = seed_gym(db, unique_slug(f"dojo-{key}"))
    scheme = next(p.scheme.model_dump() for p in PRESETS if p.key == key)
    assert client.put(URL, json=scheme, headers=as_gym(gym)).status_code == 200
    stored = client.get(URL, headers=as_gym(gym)).json()
    assert stored == scheme
    assert GradingScheme.model_validate(stored).belts


@pg
def test_a_preset_is_applied_edited_and_read_back(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "academia-grados")
    assert client.put(URL, json=BJJ, headers=as_gym(gym)).json() == BJJ

    edited = _with(
        lambda s: s["ranks"].append(
            {
                "key": "red",
                "label": "Roja",
                "target": None,
                "colors": ["#c8102e"],
                "sub_ranks": [],
            }
        )
    )
    response = client.put(URL, json=edited, headers=as_gym(gym))
    assert response.status_code == 200
    assert response.json() == edited
    assert client.get(URL, headers=as_gym(gym)).json() == response.json()
    assert stored(db, gym)["grading"] == response.json()


@pg
def test_a_change_leaves_the_other_settings_alone(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "dojo-ajustes")
    client.patch("/api/gym/settings", json={"grace_days": 9}, headers=as_gym(gym))
    client.put(URL, json=BJJ, headers=as_gym(gym))
    assert client.get("/api/gym/settings", headers=as_gym(gym)).json()["grace_days"] == 9
    # And the other way round.
    client.patch("/api/gym/settings", json={"grace_days": 3}, headers=as_gym(gym))
    assert client.get(URL, headers=as_gym(gym)).json() == BJJ


@pg
def test_a_change_reaches_only_the_current_gym(client: TestClient, db: Database) -> None:
    sur, norte = seed_gym(db, "sur-grados"), seed_gym(db, "norte-grados")
    client.put(URL, json=BJJ, headers=as_gym(sur))
    assert "grading" not in stored(db, norte)
    assert client.get(URL, headers=as_gym(norte)).json() == NONE


@pg
def test_an_invalid_scheme_is_a_422_and_changes_nothing(client: TestClient, db: Database) -> None:
    gym = seed_gym(db, "dojo-repetido")
    client.put(URL, json=BJJ, headers=as_gym(gym))
    before = stored(db, gym)
    repeated = _with(lambda s: s["kids_ladder"].append({"key": "blue", "label": "Azul"}))
    assert client.put(URL, json=repeated, headers=as_gym(gym)).status_code == 422
    assert stored(db, gym) == before


@pg
def test_a_stored_scheme_that_no_longer_fits_is_a_409_a_put_repairs(
    client: TestClient, db: Database
) -> None:
    gym = seed_gym(db, "dojo-antiguo")
    # The seed's shape before this model: sub-ranks as a count.
    old = {"ranks": [{"key": "white", "label": "Blanca", "sub_ranks": 4}]}

    async def store_old(conn: Any) -> None:
        await conn.execute(
            "UPDATE gym SET settings = settings || $2::jsonb WHERE id = $1",
            gym,
            json.dumps({"grading": old}),
        )

    run(db.admin_url, store_old)
    response = client.get(URL, headers=as_gym(gym))
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "grading_scheme_invalid"}}

    assert client.put(URL, json=BJJ, headers=as_gym(gym)).status_code == 200
    assert client.get(URL, headers=as_gym(gym)).json() == BJJ


def test_the_seed_does_not_share_the_preset() -> None:
    from app.seed.data import GRADING as seeded

    preset = next(p["scheme"] for p in grading.PRESETS if p["key"] == "bjj")
    assert seeded == preset
    # Copies all the way down, so editing the seed's never edits the preset served.
    assert seeded is not preset and seeded["ranks"] is not preset["ranks"]
    assert seeded["ranks"][0]["sub_ranks"] is not preset["ranks"][0]["sub_ranks"]
    # Nor does one rank share its sub-ranks with another.
    first, second = preset["ranks"][0]["sub_ranks"], preset["ranks"][1]["sub_ranks"]
    assert first == second and first is not second and first[0] is not second[0]


@pg
@pytest.mark.parametrize(("role", "allowed"), [("admin", True), ("coach", False)])
def test_only_an_owner_or_admin_changes_it(
    client: TestClient, db: Database, role: str, allowed: bool
) -> None:
    gym = seed_gym(db, f"dojo-{role}")
    person = staff(db, gym, role)
    response = client.put(URL, json=BJJ, headers=as_gym(gym, person))
    assert response.status_code == (200 if allowed else 403)
    assert ("grading" in stored(db, gym)) is allowed
    # A coach reads it, to award promotions against it.
    assert client.get(URL, headers=as_gym(gym, person)).status_code == 200
    assert client.get(f"{URL}/presets", headers=as_gym(gym, person)).status_code == 200
