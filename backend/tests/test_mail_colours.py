"""Emails wear the gym's theme (#515): its accent on the buttons and bars, its tints for
the text and the page, held to `tokens.css` so a token change cannot drift unseen.

The map and the rendering first, with no database; then a sent notice, which reads the
theme off its gym.
"""

import re
import uuid
from dataclasses import asdict

import pytest

from app.notices import (
    MAGIC_LINK,
    PLATFORM_LINK,
    PROOF_REJECTED,
    STAFF_INVITE,
    TEMPLATES_DIR,
    Notice,
    render,
)
from app.notices.colours import ON_ACCENT, THEMES, TOKENS, mail_colours
from app.schemas.theme import DEFAULT_THEME
from app.schemas.theme import THEMES as THEME_NAMES
from tests.pg import Database, run
from tests.test_auth_pages import _blocks
from tests.test_monthly_summary_email import BUSY
from tests.test_monthly_summary_email import notice as summary_notice
from tests.test_notices import Outbox, proof_notice, send, to_owner
from tests.test_notices import db as db
from tests.test_notices import gym as gym

PERSON = uuid.UUID("00000000-0000-4000-8000-000000000002")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    """WCAG's contrast ratio between two colours."""
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# --- the map ------------------------------------------------------------------------


def test_there_are_colours_for_every_theme() -> None:
    assert set(THEMES) == set(THEME_NAMES)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_the_map_matches_tokens_css(theme: str) -> None:
    selector = f"[data-theme='{theme}']"
    declared = next(b for s, b in _blocks().items() if selector in s.split(", "))
    colours = asdict(THEMES[theme])
    assert {key: colours[key] for key in TOKENS} == {
        key: declared[token] for key, token in TOKENS.items()
    }
    assert colours["on_accent"] == ON_ACCENT == "#ffffff"


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_each_theme_passes_aa(theme: str) -> None:
    colours = THEMES[theme]
    # White on a button, and the accent as text on the card: white, or the near-white.
    assert contrast(colours.on_accent, colours.accent) >= 4.5
    assert contrast(colours.accent, "#ffffff") >= 4.5
    assert contrast(colours.accent, colours.surface) >= 4.5
    # Text on the card, and the footer's on the page.
    for text in (colours.text, colours.text_muted, colours.heading):
        assert contrast(text, colours.surface) >= 4.5
    assert contrast(colours.text_subtle, colours.bg) >= 4.5


def test_an_unknown_or_missing_theme_is_bosque() -> None:
    assert DEFAULT_THEME == "bosque"
    assert mail_colours("neon") == THEMES["bosque"]
    assert mail_colours(None) == THEMES["bosque"]
    assert mail_colours("oceano") == THEMES["oceano"]


# --- the rendering ------------------------------------------------------------------


def test_no_template_keeps_a_colour_of_its_own() -> None:
    """Every template takes its colours from `colours`, none from a hex of its own."""
    for path in sorted(TEMPLATES_DIR.glob("*.html")):
        source = re.sub(r"\{#.*?#\}", "", path.read_text(), flags=re.S)
        assert not HEX.findall(source), path.name


def summary_html(theme: str | None) -> str:
    html = render(
        summary_notice(BUSY), unsubscribe_url="https://x/u", app_url="https://x", theme=theme
    ).html
    assert html is not None
    return html


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_each_theme_renders_its_accent_in_the_button_and_the_bars(theme: str) -> None:
    colours = THEMES[theme]
    html = summary_html(theme)

    assert f"background:{colours.accent};color:#ffffff;" in html
    assert f'width="18%" height="8" bgcolor="{colours.accent}"' in html
    # The headline figures in the accent.
    assert (
        html.count(f"font-size:32px;line-height:1.2;font-weight:700;color:{colours.accent};") == 2
    )
    # The bar's empty part, the card and the page in the theme's tints.
    assert f'bgcolor="{colours.track}"' in html
    assert f'bgcolor="{colours.surface}"' in html
    assert f'<body bgcolor="{colours.bg}"' in html
    # No other theme's accent, and none of the old neutral greys.
    for other in THEMES.values():
        if other.accent != colours.accent:
            assert other.accent not in html
    assert "#18181b" not in html and "#52525b" not in html


def test_an_unknown_theme_renders_as_bosque() -> None:
    assert summary_html("neon") == summary_html("bosque") == summary_html(None)


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_every_colour_in_an_email_is_one_of_its_themes(theme: str) -> None:
    allowed = set(asdict(THEMES[theme]).values())
    staff = {
        "name": "Pedro",
        "gym": "Academia Sur",
        "inviter": "Carla",
        "roles": ["Coach"],
        "can": ["attendance"],
    }
    link = {"name": "A", "url": "https://x", "code": "123456"}
    emails = [
        render(
            summary_notice(BUSY), unsubscribe_url="https://x/u", app_url="https://x", theme=theme
        ),
        render(proof_notice(), page_url="https://x/p", theme=theme),
        render(proof_notice(PROOF_REJECTED, note="Borroso"), page_url="https://x/p", theme=theme),
        render(proof_notice(), page_url="https://x/p", page_code="654321", theme=theme),
        render(
            Notice(STAFF_INVITE, "p@example.cl", PERSON, None, staff),
            page_url="https://x/p",
            theme=theme,
        ),
        render(Notice(MAGIC_LINK, "a@example.cl", PERSON, None, link), theme=theme),
        render(Notice(PLATFORM_LINK, "a@example.cl", PERSON, None, link), theme=theme),
    ]
    for email in emails:
        assert email.html is not None
        assert set(HEX.findall(email.html)) <= allowed, email.subject
        # Every value made it in: none is left as a literal `{{ … }}` (#517's review).
        assert "{{" not in email.html and "}}" not in email.html, email.subject
    # The summary's secondary lines, which build their style in a `{% set %}`.
    summary = emails[0].html or ""
    assert summary.count(f"color:{THEMES[theme].text_muted};") >= 6


def test_no_template_writes_a_value_inside_a_tag() -> None:
    """`{{ … }}` inside `{% … %}` is a string, never rendered: every template, so a
    colour in a `{% set %}` style cannot slip through as text again."""
    for path in sorted(TEMPLATES_DIR.glob("*")):
        tags = re.findall(r"\{%.*?%\}", path.read_text(), flags=re.S)
        assert not [t for t in tags if "{{" in t or "}}" in t], path.name


def test_a_platform_link_wears_bosque() -> None:
    # As `app.platform.web` renders it: no gym, so no theme.
    link = {"name": "A", "url": "https://x", "code": "123456"}
    html = render(Notice(PLATFORM_LINK, "a@example.cl", PERSON, None, link)).html
    assert html is not None
    assert f"background:{THEMES['bosque'].accent};color:#ffffff;" in html


def test_rakins_footer_mark_is_unchanged() -> None:
    html = render(proof_notice(), logo_url="https://x/email-logo.png", theme="volcan").html
    assert html is not None
    assert '<img src="https://x/email-logo.png" alt="Rakin" width="69" height="20"' in html


# --- a sent notice ------------------------------------------------------------------


@pytest.mark.postgres
@pytest.mark.parametrize("theme", sorted(THEMES))
def test_a_sent_notice_wears_its_gyms_theme(db: Database, gym: uuid.UUID, theme: str) -> None:
    run(db.admin_url, lambda c: c.execute("UPDATE gym SET theme = $1 WHERE id = $2", theme, gym))
    outbox = Outbox()

    send(db, to_owner(gym), outbox)

    [email] = outbox.sent
    assert email.html is not None
    assert f"background:{THEMES[theme].accent};color:#ffffff;" in email.html
