"""The colours an email wears: its gym's theme (#199, #515), as the app does.

Each theme's handful of email colours is a copy of `frontend/src/styles/tokens.css`'s
values for that theme, by the token each one is (`TOKENS`); `tests/test_mail_colours.py`
holds the copies to the file, so a token changed there cannot drift here unseen. Mail
clients read no CSS variables, so the templates write these values inline, in `style`
and in `bgcolor`.

The accent fills the buttons and the bars and colours the summary's headline figures,
with white on it: every theme's accent is 4.5:1 or more against white either way. Mail
of no gym (a platform operator's sign-in link), and a theme this map does not know,
wear the default, Bosque.
"""

from dataclasses import dataclass, fields

from app.schemas.theme import DEFAULT_THEME


@dataclass(frozen=True)
class MailColours:
    # The page behind the card, and the card itself.
    bg: str
    surface: str
    # A quoted note's well, and its left edge.
    well: str
    well_edge: str
    # A rule between rows, and the empty part of a bar.
    divider: str
    track: str
    # Body text, secondary lines, the footer's faintest; titles and the sign-in code.
    text: str
    text_muted: str
    text_subtle: str
    heading: str
    # Buttons, bars, links and headline figures, and the text on a button.
    accent: str
    on_accent: str


# Which token in `tokens.css` each colour is. `on_accent` is no token: it is white.
TOKENS: dict[str, str] = {
    "bg": "--color-bg",
    "surface": "--color-surface",
    "well": "--color-surface-sunken",
    "well_edge": "--color-border-strong",
    "divider": "--color-divider",
    "track": "--color-accent-soft",
    "text": "--color-text",
    "text_muted": "--color-text-muted",
    "text_subtle": "--color-text-subtle",
    "heading": "--color-heading",
    "accent": "--color-accent",
}
ON_ACCENT = "#ffffff"

THEMES: dict[str, MailColours] = {
    "bosque": MailColours(
        bg="#f6f8f1",
        surface="#fcfdf9",
        well="#ebeee6",
        well_edge="#b3baad",
        divider="#eaeee6",
        track="#e3edde",
        text="#102719",
        text_muted="#57685a",
        text_subtle="#5e6c60",
        heading="#153c25",
        accent="#23643f",
        on_accent=ON_ACCENT,
    ),
    "oceano": MailColours(
        bg="#f2f8fd",
        surface="#fafdff",
        well="#e6eef5",
        well_edge="#adb9c4",
        divider="#e7eef3",
        track="#deebf8",
        text="#102334",
        text_muted="#556574",
        text_subtle="#5e6c78",
        heading="#15364f",
        accent="#225984",
        on_accent=ON_ACCENT,
    ),
    "volcan": MailColours(
        bg="#fdf4f4",
        surface="#fffbfb",
        well="#f5eaea",
        well_edge="#c4b3b2",
        divider="#f3eaea",
        track="#f8e4e4",
        text="#32191a",
        text_muted="#745d5d",
        text_subtle="#7a6666",
        heading="#4d2527",
        accent="#803f42",
        on_accent=ON_ACCENT,
    ),
}

assert set(TOKENS) | {"on_accent"} == {f.name for f in fields(MailColours)}


def mail_colours(theme: str | None) -> MailColours:
    """The colours of `theme`; Bosque's for none, or for one this map does not know."""
    return THEMES.get(theme or DEFAULT_THEME, THEMES[DEFAULT_THEME])
