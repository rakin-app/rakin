# /// script
# requires-python = ">=3.13"
# dependencies = ["fonttools[woff]>=4.60", "uharfbuzz>=0.50", "resvg-py>=0.2", "pillow>=11"]
# ///
"""Builds Rakin's logo files (#224) from the geometry below.

    uv run docs/brand/build.py [--fonts DIR]

Writes the source SVGs to `docs/brand/` and the icons the app serves to
`frontend/public/`. The wordmark is outlined from Bricolage Grotesque 600 (the
display font, #199) and the Open Graph tagline from Figtree 500, so no file
depends on a font being installed. `--fonts` is the directory holding
`bricolage-grotesque-latin-600-normal.woff2` and `figtree-latin-500-normal.woff2`;
by default, the copies `npm install` puts under `frontend/node_modules/@fontsource`.

The symbol is drawn on a 32-unit grid with every edge on an even unit, so at
16 px each edge lands on a whole pixel.
"""

import argparse
import io
from pathlib import Path

import resvg_py
import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "docs" / "brand"
PUBLIC = ROOT / "frontend" / "public"
FONTSOURCE = ROOT / "frontend" / "node_modules" / "@fontsource"

# Bosque, Rakin's own theme (frontend/src/styles/tokens.css, #199).
PRIMARY = "#153c25"  # --color-inverse: the tile
INK = "#f5f6eb"  # --color-inverse-text: the mats
ACCENT = "#a0c79b"  # --color-moss: the centre mat, the ring, and the square on dark
ACCENT_DEEP = "#4e7f58"  # --color-focus: the square on light ground
HEADING = "#153c25"  # --color-heading: the wordmark on light ground
SIDEBAR_TEXT = "#e5ebd8"  # --color-sidebar-text: the wordmark on dark ground
HERO_FROM, HERO_TO = "#0f3620", "#072014"  # --gradient-hero

# Four mats turning around a half mat (the 4½-mat tatami layout).
MATS = ((4, 4, 16, 6), (22, 4, 6, 16), (12, 22, 16, 6), (4, 12, 6, 16))
CENTRE = (12, 12, 8, 8)
# The wordmark's square period, in em: the centre mat's shape, at the text's scale.
SQUARE_EM, SQUARE_GAP_EM = 0.21, 0.06
TRACKING_EM = -0.02


def rect(x: float, y: float, w: float, h: float, fill: str, rx: float = 1) -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"/>'


def marks(ink: str = INK, accent: str = ACCENT) -> str:
    return "".join(rect(*m, ink) for m in MATS) + rect(*CENTRE, accent)


TILE = rect(0, 0, 32, 32, PRIMARY, rx=7)
# A 2-unit ring in the accent at the tile's edge, part of the mark (the owner's C1):
# dark surfaces would swallow the dark tile without it.
RING = f'<rect x="1" y="1" width="30" height="30" rx="6" fill="none" stroke="{ACCENT}" stroke-opacity="0.6" stroke-width="2"/>'


def svg(width: float, height: float, body: str, view: str | None = None, size: bool = True) -> str:
    dims = f' width="{width:g}" height="{height:g}"' if size else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view or f"0 0 {width:g} {height:g}"}"{dims}>'
        f"{body}</svg>\n"
    )


def symbol() -> str:
    return svg(32, 32, TILE + RING + marks())


def apple_touch() -> str:
    # Square: iOS cuts its own rounded corners, about where the tile's would be.
    return svg(32, 32, rect(0, 0, 32, 32, PRIMARY, rx=0) + RING + marks())


def maskable() -> str:
    # Full bleed; the mats scaled into the safe zone (a circle of 80% the width).
    return svg(32, 32, rect(0, 0, 32, 32, PRIMARY, rx=0) + f'<g transform="translate(16 16) scale(0.66) translate(-16 -16)">{marks()}</g>')


class Outliner:
    """Text as SVG paths: shaped by HarfBuzz (kerning included), drawn by fontTools."""

    def __init__(self, path: Path) -> None:
        self.font = TTFont(path)
        self.upm = self.font["head"].unitsPerEm
        # HarfBuzz reads no WOFF2: hand it the font as plain sfnt.
        sfnt = io.BytesIO()
        flavor, self.font.flavor = self.font.flavor, None
        self.font.save(sfnt)
        self.font.flavor = flavor
        self.hb_font = hb.Font(hb.Face(sfnt.getvalue()))
        self.glyphs = self.font.getGlyphSet()
        self.order = self.font.getGlyphOrder()

    def path(self, text: str, size: float, x: float, baseline: float, tracking_em: float = 0) -> tuple[str, float]:
        """`text` at `size`, its baseline at `baseline`; returns the path and the pen's x after it."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb_font, buf, {"kern": True, "liga": True})
        scale = size / self.upm
        pen = SVGPathPen(self.glyphs)
        cursor = 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions, strict=True):
            name = self.order[info.codepoint]
            # Font units, y up → user units, y down.
            t = (scale, 0, 0, -scale, x + (cursor + pos.x_offset) * scale, baseline - pos.y_offset * scale)
            self.glyphs[name].draw(TransformPen(pen, t))
            cursor += pos.x_advance + tracking_em * self.upm
        return pen.getCommands(), x + cursor * scale

    def top(self, text: str, size: float) -> float:
        """How far above the baseline `text`'s tallest glyph reaches."""
        glyf, cmap = self.font["glyf"], self.font.getBestCmap()
        return max(glyf[cmap[ord(ch)]].yMax for ch in text) * size / self.upm


def wordmark(display: Outliner, x: float, baseline: float, size: float, text_fill: str, square_fill: str) -> tuple[str, float]:
    """`rakin` and its square period; returns the markup and its right edge."""
    d, end = display.path("rakin", size, x, baseline, TRACKING_EM)
    side = SQUARE_EM * size
    sx = end + SQUARE_GAP_EM * size
    body = f'<path d="{d}" fill="{text_fill}"/>' + rect(round(sx, 2), round(baseline - side, 2), round(side, 2), round(side, 2), square_fill, rx=round(side * 0.1, 2))
    return body, sx + side


def lockup(display: Outliner, on_dark: bool) -> str:
    """Symbol and wordmark side by side, for a 32-unit-high symbol (ui-design-v3's proportions)."""
    size = 0.82 * 32
    x = 32 + 0.28 * 32
    # The letters' visual middle on the symbol's middle.
    baseline = 16 + display.top("rakin", size) / 2
    text_fill, square_fill = (SIDEBAR_TEXT, ACCENT) if on_dark else (HEADING, ACCENT_DEEP)
    body, right = wordmark(display, x, baseline, size, text_fill, square_fill)
    width = round(right + 0.5, 1)
    return svg(width, 32, TILE + RING + marks() + body)


def og_image(display: Outliner, body_font: Outliner) -> str:
    """1200×630, for link previews of rakin.app: the lockup on the hero gradient, and the line under it."""
    w, h = 1200, 630
    scale = 4.5  # the 32-unit lockup at 144 px high
    lock = lockup(display, on_dark=True)
    inner = lock[lock.index(">") + 1 : lock.rindex("</svg>")]
    lock_w = float(lock.split('width="')[1].split('"')[0])
    lx, ly = (w - lock_w * scale) / 2, 196
    tagline = "Membresías y pagos para academias"
    t_size = 40
    _, t_end = body_font.path(tagline, t_size, 0, 0)
    t_x = (w - t_end) / 2
    t_path, _ = body_font.path(tagline, t_size, t_x, ly + 32 * scale + 92)
    defs = (
        f'<defs><linearGradient id="hero" x1="0" y1="0" x2="0.35" y2="1">'
        f'<stop offset="0" stop-color="{HERO_FROM}"/><stop offset="1" stop-color="{HERO_TO}"/></linearGradient></defs>'
    )
    body = (
        defs
        + f'<rect width="{w}" height="{h}" fill="url(#hero)"/>'
        + f'<g transform="translate({lx:.1f} {ly}) scale({scale})">{inner}</g>'
        + f'<path d="{t_path}" fill="{INK}" fill-opacity="0.78"/>'
    )
    return svg(w, h, body)


def png(markup: str, width: int | None = None, height: int | None = None, zoom: float | None = None) -> bytes:
    if zoom is not None:
        return bytes(resvg_py.svg_to_bytes(svg_string=markup, zoom=zoom, skip_system_fonts=True))
    return bytes(resvg_py.svg_to_bytes(svg_string=markup, width=width, height=height or width, skip_system_fonts=True))


def ico(markup: str, sizes: tuple[int, ...]) -> bytes:
    # Each size rendered from the vector, not downscaled from the largest.
    images = [Image.open(io.BytesIO(png(markup, s))).convert("RGBA") for s in sizes]
    out = io.BytesIO()
    images[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[:-1])
    return out.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Builds Rakin's logo files (#224).")
    parser.add_argument("--fonts", type=Path, help="directory with the two .woff2 files")
    args = parser.parse_args()
    display_path = (args.fonts / "bricolage-grotesque-latin-600-normal.woff2") if args.fonts else FONTSOURCE / "bricolage-grotesque/files/bricolage-grotesque-latin-600-normal.woff2"
    body_path = (args.fonts / "figtree-latin-500-normal.woff2") if args.fonts else FONTSOURCE / "figtree/files/figtree-latin-500-normal.woff2"
    display, body_font = Outliner(display_path), Outliner(body_path)

    PUBLIC.mkdir(exist_ok=True)
    sources = {
        "symbol.svg": symbol(),
        "symbol-maskable.svg": maskable(),
        "lockup.svg": lockup(display, on_dark=False),
        "lockup-dark.svg": lockup(display, on_dark=True),
        "og-image.svg": og_image(display, body_font),
    }
    for name, markup in sources.items():
        (BRAND / name).write_text(markup)

    files = {
        "favicon.svg": sources["symbol.svg"].encode(),
        # .ico for what does not take an SVG icon.
        "favicon.ico": ico(sources["symbol.svg"], (16, 32, 48)),
        "apple-touch-icon.png": png(apple_touch(), 180),
        "icon-192.png": png(sources["symbol.svg"], 192),
        "icon-512.png": png(sources["symbol.svg"], 512),
        "icon-maskable-512.png": png(sources["symbol-maskable.svg"], 512),
        "og-image.png": png(sources["og-image.svg"], 1200, 630),
        # The email footer's mark: 2× for a 20 px-high <img>.
        "email-logo.png": png(sources["lockup.svg"], zoom=40 / 32),
    }
    for name, data in files.items():
        (PUBLIC / name).write_bytes(data)
    print(f"wrote {len(sources)} sources to {BRAND.relative_to(ROOT)}/ and {len(files)} files to {PUBLIC.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
