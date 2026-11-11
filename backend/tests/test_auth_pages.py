"""The sign-in link's pages look as the app does: the same tokens, and fonts the SPA serves.

They are plain HTML from the API, with copies of the frontend's values; these hold the
copies to the originals, so a token changed in `tokens.css` cannot drift here unseen.
"""

import re
from pathlib import Path

from app.auth import FONTS, STYLESHEET, THEME_TOKENS, TOKENS

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def _blocks() -> dict[str, dict[str, str]]:
    """Each rule of `tokens.css` by its selector, as its declarations."""
    css = re.sub(r"/\*.*?\*/", "", (FRONTEND / "src/styles/tokens.css").read_text(), flags=re.S)
    return {
        " ".join(selector.split()): dict(re.findall(r"(--[\w-]+):\s*([^;]+);", body))
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    }


def test_the_pages_use_the_apps_tokens() -> None:
    root = _blocks()[":root"]
    assert {name: root.get(name) for name in TOKENS} == TOKENS


def test_the_pages_wear_each_theme_as_the_app_does() -> None:
    blocks = _blocks()
    for theme, colours in THEME_TOKENS.items():
        selector = f"[data-theme='{theme}']"
        declared = next(b for s, b in blocks.items() if selector in s.split(", "))
        assert {name: declared.get(name) for name in colours} == colours, theme
    # The first is the default, as `:root` has it in the app.
    first = next(iter(THEME_TOKENS))
    assert f":root, [data-theme='{first}']" in blocks
    assert f":root,[data-theme='{first}']{{" in STYLESHEET


def test_every_font_the_pages_load_is_one_the_spa_serves() -> None:
    vite = (FRONTEND / "vite.config.ts").read_text()
    for _, _, file in FONTS:
        assert f"/files/{file}.woff2'" in vite
        assert f"url(/fonts/{file}.woff2)" in STYLESHEET


def test_the_pages_stay_light() -> None:
    assert "color-scheme:light" in STYLESHEET
