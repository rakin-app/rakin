"""The sign-in link's pages look as the app does: the same tokens, and fonts the SPA serves.

They are plain HTML from the API, with copies of the frontend's values; these hold the
copies to the originals, so a token changed in `tokens.css` cannot drift here unseen.
"""

import re
from pathlib import Path

from app.auth import FONTS, STYLESHEET, TOKENS

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def test_the_pages_use_the_apps_tokens() -> None:
    css = (FRONTEND / "src/styles/tokens.css").read_text()
    declared = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", css))
    assert {name: declared.get(name) for name in TOKENS} == TOKENS


def test_every_font_the_pages_load_is_one_the_spa_serves() -> None:
    vite = (FRONTEND / "vite.config.ts").read_text()
    for _, _, file in FONTS:
        assert f"/files/{file}.woff2'" in vite
        assert f"url(/fonts/{file}.woff2)" in STYLESHEET


def test_the_pages_stay_light() -> None:
    assert "color-scheme:light" in STYLESHEET
