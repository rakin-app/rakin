"""A gym's logo (#223): the image the owner uploads, as the files the app shows.

The owner picks a PNG, JPEG or WebP of up to `MAX_LOGO_BYTES` and drags a square over
it in the browser; the API gets the file as picked and that square (`Crop`), and makes
`VARIANTS` of it here: WebP at 512, 128 and 64 px for the app, and a PNG for email,
whose clients do not all read WebP. Each is drawn afresh from the pixels, so nothing
the original carried (EXIF, a location, a camera's notes) is kept. SVG is never taken:
it is a document that can carry script.

The files live in the blob store under `logos/<gym_id>/<version>/`, and `gym.logo_version`
(0040) names the current set. An upload is a new version and the old set is deleted,
so a URL never changes what it shows and is cached for good (`app.api.logos`).
"""

import io
import secrets
import uuid
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

# What the owner may pick, by the format the bytes really are, not what they claim.
FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
CONTENT_TYPES = frozenset(FORMATS.values())
MAX_LOGO_BYTES = 5 * 1024 * 1024
# A 5 MB file can still unpack to a vast image; far past any camera's, refuse it.
MAX_PIXELS = 50_000_000


@dataclass(frozen=True)
class Variant:
    size: int
    format: str
    content_type: str


# By file name, as served under the version's path.
VARIANTS = {
    "512.webp": Variant(512, "WEBP", "image/webp"),
    "128.webp": Variant(128, "WEBP", "image/webp"),
    "64.webp": Variant(64, "WEBP", "image/webp"),
    # For email: shown at 48 px, sharp on a dense screen.
    "128.png": Variant(128, "PNG", "image/png"),
}
EMAIL_VARIANT = "128.png"

PATH_PREFIX = "/api/logos"


class LogoRefused(ValueError):
    """Why an upload is not a logo, as a code the web app words (`logo_*`)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Crop:
    """The square to keep, in pixels of the picture as it is shown upright."""

    x: int
    y: int
    size: int


def new_version() -> str:
    return secrets.token_hex(8)


def key(gym_id: uuid.UUID, version: str, variant: str) -> str:
    return f"logos/{gym_id}/{version}/{variant}"


def logo_path(gym_id: uuid.UUID, version: str | None) -> str | None:
    """Where the web app finds the logo's files, `<path>/<variant>`; None with no logo."""
    return None if version is None else f"{PATH_PREFIX}/{gym_id}/{version}"


def make_variants(data: bytes, crop: Crop | None) -> dict[str, bytes]:
    """`VARIANTS` of the picture `data` is, cut to `crop` (the middle square when None).

    Raises `LogoRefused` for anything that is not a PNG, JPEG or WebP, or is too large."""
    if len(data) > MAX_LOGO_BYTES:
        raise LogoRefused("logo_too_large")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            # Reads only the header: the size is known before any pixel is unpacked.
            opened = Image.open(io.BytesIO(data), formats=list(FORMATS))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise LogoRefused("logo_too_large") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise LogoRefused("logo_unreadable") from None
    if opened.width * opened.height > MAX_PIXELS:
        raise LogoRefused("logo_too_large")
    try:
        opened.load()
    except (OSError, SyntaxError, ValueError):
        # Truncated or corrupt: it says it is an image and is not one.
        raise LogoRefused("logo_unreadable") from None
    # Upright, as the browser showed it when the square was drawn.
    image = ImageOps.exif_transpose(opened).convert("RGBA")
    square = _square(image.width, image.height, crop)
    image = image.crop(square)
    out: dict[str, bytes] = {}
    for name, variant in VARIANTS.items():
        sized = image.resize((variant.size, variant.size), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        if variant.format == "WEBP":
            sized.save(buffer, "WEBP", quality=88, method=6)
        else:
            sized.save(buffer, "PNG", optimize=True)
        out[name] = buffer.getvalue()
    return out


def _square(width: int, height: int, crop: Crop | None) -> tuple[int, int, int, int]:
    """`crop` held inside the picture, as Pillow's box; the middle square when None."""
    side = min(width, height)
    if crop is None:
        x, y = (width - side) // 2, (height - side) // 2
    else:
        side = max(1, min(crop.size, side))
        x = min(max(crop.x, 0), width - side)
        y = min(max(crop.y, 0), height - side)
    return (x, y, x + side, y + side)
