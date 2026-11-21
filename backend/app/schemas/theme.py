"""A gym's theme (#199): the colours its app, student page, sign-in pages and emails
(#515, `app.notices.colours`) wear.

`gym.theme` (0039) holds one of these; the first is the default. The frontend keeps
the same list in `src/theme.ts`, and `tokens.css` a block of colours for each.
"""

from typing import Literal, get_args

Theme = Literal["bosque", "oceano", "volcan"]

THEMES: tuple[str, ...] = get_args(Theme)
DEFAULT_THEME: Theme = "bosque"
