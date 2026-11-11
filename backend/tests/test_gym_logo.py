"""A gym's logo (#223): what an upload becomes, who may change it, and who may read it.

The pages before sign-in and the emails are covered where the rest of each is: the
host and the sign-in link's pages in `tests/test_gym_hosts.py`, the email header here.
"""

import io
import uuid
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.logos import MAX_LOGO_BYTES, VARIANTS, Crop, LogoRefused, make_variants
from app.main import create_app
from app.notices import WELCOME, Notice, render
from tests.auth import FakeAuth, as_gym
from tests.conftest import make_settings, require_test_database_url
from tests.pg import Database, migrate, run, seed_gym, throwaway_database

RED, GREEN, BLUE = (255, 0, 0), (0, 160, 0), (0, 0, 255)


def picture(
    fmt: str = "PNG", size: tuple[int, int] = (300, 200), colour: tuple[int, int, int] = RED
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, fmt)
    return buffer.getvalue()


def opened(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


# --- what an upload becomes, no database ------------------------------------------------


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_each_format_becomes_every_variant_square(fmt: str) -> None:
    variants = make_variants(picture(fmt), None)
    assert set(variants) == set(VARIANTS)
    for name, data in variants.items():
        image = opened(data)
        assert image.format == VARIANTS[name].format
        assert image.size == (VARIANTS[name].size, VARIANTS[name].size)


def test_the_square_drawn_is_the_one_kept() -> None:
    # Red on the left, blue on the right: the right-hand square is all blue.
    image = Image.new("RGB", (200, 100), RED)
    image.paste(BLUE, (100, 0, 200, 100))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    kept = opened(make_variants(buffer.getvalue(), Crop(100, 0, 100))["128.png"])
    assert kept.convert("RGB").getpixel((64, 64)) == BLUE


def test_a_square_past_the_edge_is_held_inside_the_picture() -> None:
    kept = make_variants(picture(size=(200, 100)), Crop(150, 80, 500))
    assert opened(kept["64.webp"]).size == (64, 64)


def test_the_picture_is_cut_upright_and_keeps_none_of_its_metadata() -> None:
    # Upright it is tall, red over green over blue; the camera stored it on its side,
    # with an orientation that says so, and its own name.
    upright = Image.new("RGB", (100, 300), RED)
    upright.paste(GREEN, (0, 100, 100, 200))
    upright.paste(BLUE, (0, 200, 100, 300))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to show
    exif[0x010F] = "Cámara de prueba"
    buffer = io.BytesIO()
    upright.transpose(Image.Transpose.ROTATE_90).save(buffer, "JPEG", exif=exif, quality=95)

    variants = make_variants(buffer.getvalue(), Crop(0, 200, 100))

    # The bottom square of the upright picture: blue, not the red the stored one starts with.
    red, green, blue = opened(variants["128.png"]).convert("RGB").getpixel((64, 64))  # type: ignore[misc]
    assert blue > 200 and red < 60 and green < 60
    for data in variants.values():
        image = opened(data)
        assert not image.getexif()
        assert "exif" not in image.info and "xmp" not in image.info


@pytest.mark.parametrize(
    "data",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        picture("GIF"),
        picture("BMP"),
        picture()[:200],  # a PNG cut short
        b"",
    ],
    ids=["svg", "gif", "bmp", "truncated", "empty"],
)
def test_anything_but_a_png_jpeg_or_webp_is_refused(data: bytes) -> None:
    with pytest.raises(LogoRefused) as refused:
        make_variants(data, None)
    assert refused.value.code == "logo_unreadable"


def test_a_file_past_the_limit_is_refused() -> None:
    with pytest.raises(LogoRefused) as refused:
        make_variants(b"\x00" * (MAX_LOGO_BYTES + 1), None)
    assert refused.value.code == "logo_too_large"


def test_a_small_file_of_vast_dimensions_is_refused_before_it_is_unpacked() -> None:
    buffer = io.BytesIO()
    Image.new("1", (8000, 8000)).save(buffer, "PNG")
    assert len(buffer.getvalue()) < MAX_LOGO_BYTES
    with pytest.raises(LogoRefused) as refused:
        make_variants(buffer.getvalue(), None)
    assert refused.value.code == "logo_too_large"


# --- the email header ------------------------------------------------------------------

GYM, PERSON = uuid.uuid4(), uuid.uuid4()
WELCOME_CONTEXT = {
    "gym": "Academia <Sur>",
    "name": "Ana",
    "plan_name": "Mensual",
    "dependent_name": None,
    "bank_account": None,
}


def test_an_email_of_a_gym_with_a_logo_shows_it_round_named_for_the_gym() -> None:
    url = "https://academia-sur.rakin.app/api/logos/x/0123456789abcdef/128.png"
    email = render(Notice(WELCOME, "ana@example.cl", PERSON, GYM, WELCOME_CONTEXT), logo_url=url)
    assert email.html is not None
    assert f'<img src="{url}" alt="Academia &lt;Sur&gt;"' in email.html
    assert "border-radius:50%" in email.html
    assert url not in email.text


def test_an_email_of_a_gym_with_no_logo_has_no_image() -> None:
    email = render(Notice(WELCOME, "ana@example.cl", PERSON, GYM, WELCOME_CONTEXT))
    assert email.html is not None
    assert "<img" not in email.html


# --- the API, against real Postgres -------------------------------------------------------

pg = pytest.mark.postgres

URL = "/api/gym/logo"


@pytest.fixture(scope="module")
def db() -> Iterator[Database]:
    with throwaway_database(require_test_database_url()) as database:
        migrate(database)
        yield database


@pytest.fixture(scope="module")
def blobs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("blobs")


@pytest.fixture(scope="module")
def client(db: Database, blobs: Path) -> Iterator[TestClient]:
    settings = make_settings(
        database_url=db.api_url,
        public_base_url="https://rakin.app",
        base_domain="rakin.app",
        blob_store="local",
        blob_local_dir=blobs,
    )
    app = create_app(settings)
    app.add_middleware(FakeAuth)
    with TestClient(app) as c:
        yield c


def upload(
    client: TestClient,
    gym: uuid.UUID,
    data: bytes,
    content_type: str = "image/png",
    query: str = "",
    person: uuid.UUID | None = None,
) -> tuple[int, dict[str, object]]:
    response = client.put(
        f"{URL}{query}",
        content=data,
        headers={**as_gym(gym, person), "Content-Type": content_type},
    )
    return response.status_code, response.json()


def files(blobs: Path, gym: uuid.UUID) -> set[str]:
    root = blobs / "data" / "logos" / str(gym)
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def coach_of(db: Database, gym: uuid.UUID) -> uuid.UUID:
    coach = uuid.uuid4()

    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute("INSERT INTO person (id, name) VALUES ($1, 'x')", coach)
        await conn.execute(
            "INSERT INTO gym_person (gym_id, person_id, name) VALUES ($1, $2, 'x')", gym, coach
        )
        await conn.execute(
            "INSERT INTO staff (gym_id, person_id, role) VALUES ($1, $2, 'coach')", gym, coach
        )

    run(db.admin_url, query)
    return coach


@pg
def test_an_upload_is_served_to_anyone_cached_for_good(
    client: TestClient, db: Database, blobs: Path
) -> None:
    gym = seed_gym(db, "logo-sube")
    status, settings = upload(client, gym, picture(), query="?x=50&y=0&size=200")
    assert status == 200
    logo = settings["logo"]
    assert isinstance(logo, str) and logo.startswith(f"/api/logos/{gym}/")
    assert client.get("/api/gym/settings", headers=as_gym(gym)).json()["logo"] == logo
    assert client.get("/api/me/role", headers=as_gym(gym)).json()["gym_logo"] == logo

    # No session: a sign-in page or an email client fetches it.
    for variant, spec in VARIANTS.items():
        served = client.get(f"{logo}/{variant}")
        assert served.status_code == 200
        assert served.headers["content-type"] == spec.content_type
        assert "immutable" in served.headers["cache-control"]
        assert served.headers["x-content-type-options"] == "nosniff"
        assert opened(served.content).size == (spec.size, spec.size)
    assert client.get(f"{logo}/original.jpg").status_code == 404
    assert client.get(f"{logo}/../../../settings").status_code == 404


@pg
def test_a_replacement_is_a_new_url_and_the_old_files_are_gone(
    client: TestClient, db: Database, blobs: Path
) -> None:
    gym = seed_gym(db, "logo-cambia")
    _, first = upload(client, gym, picture(colour=RED))
    _, second = upload(client, gym, picture("JPEG", colour=BLUE), "image/jpeg")
    assert first["logo"] != second["logo"]
    assert client.get(f"{first['logo']}/128.webp").status_code == 404
    assert client.get(f"{second['logo']}/128.webp").status_code == 200
    version = str(second["logo"]).rsplit("/", 1)[1]
    assert files(blobs, gym) == {f"{version}/{v}" for v in VARIANTS}


@pg
def test_quitar_logo_removes_it_and_its_files(
    client: TestClient, db: Database, blobs: Path
) -> None:
    gym = seed_gym(db, "logo-quita")
    _, settings = upload(client, gym, picture())
    response = client.delete(URL, headers=as_gym(gym))
    assert response.status_code == 200
    assert response.json()["logo"] is None
    assert client.get("/api/me/role", headers=as_gym(gym)).json()["gym_logo"] is None
    assert client.get(f"{settings['logo']}/64.webp").status_code == 404
    assert files(blobs, gym) == set()
    # Removing none is no error.
    assert client.delete(URL, headers=as_gym(gym)).status_code == 200


@pg
@pytest.mark.parametrize(
    ("content_type", "data", "query", "status", "code"),
    [
        ("image/svg+xml", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "", 415, "logo_type"),
        ("image/gif", picture("GIF"), "", 415, "logo_type"),
        # Claims to be a PNG, and is an SVG.
        ("image/png", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "", 422, "logo_unreadable"),
        ("image/png", b"\x89PNG" + b"\x00" * MAX_LOGO_BYTES, "", 413, "logo_too_large"),
        ("image/png", picture(), "?x=0&y=0", 422, "logo_crop"),
    ],
    ids=["svg", "gif", "svg-as-png", "too-large", "half-a-square"],
)
def test_what_is_no_logo_is_refused_and_changes_nothing(
    client: TestClient,
    db: Database,
    blobs: Path,
    content_type: str,
    data: bytes,
    query: str,
    status: int,
    code: str,
) -> None:
    gym = seed_gym(db, f"logo-no-{uuid.uuid4().hex[:6]}")
    got, body = upload(client, gym, data, content_type, query)
    assert (got, body["detail"]) == (status, code)
    assert client.get("/api/gym/settings", headers=as_gym(gym)).json()["logo"] is None
    assert files(blobs, gym) == set()


@pg
def test_a_coach_may_not_change_the_logo(client: TestClient, db: Database, blobs: Path) -> None:
    gym = seed_gym(db, "logo-coach")
    coach = coach_of(db, gym)
    status, _ = upload(client, gym, picture(), person=coach)
    assert status == 403
    assert client.delete(URL, headers=as_gym(gym, coach)).status_code == 403
    assert files(blobs, gym) == set()


@pg
def test_an_upload_needs_a_session(client: TestClient, db: Database) -> None:
    response = client.put(URL, content=picture(), headers={"Content-Type": "image/png"})
    assert response.status_code == 401


@pg
def test_the_database_holds_the_version_to_a_path_segment(db: Database) -> None:
    gym = seed_gym(db, "logo-check")

    async def query(conn: asyncpg.Connection) -> None:
        await conn.execute("UPDATE gym SET logo_version = '../x' WHERE id = $1", gym)

    with pytest.raises(asyncpg.CheckViolationError):
        run(db.admin_url, query)
