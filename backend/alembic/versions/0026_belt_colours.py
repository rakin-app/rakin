"""Belt colours: fill them in on the grading schemes stored before ranks had any (#135).

A rank of the scheme in `gym.settings.grading` may now carry `colors`, its belt's. The
BJJ preset comes with them; a scheme applied from it before keeps none and would show
its ranks as labels. So a stored scheme whose ranks hold all five adult belts of that
preset, matched by label ignoring case and accents, gets the preset's colours on each
rank in either ladder whose label is one of the preset's and that has none. Anything
else is left as it is: a scheme of other ranks, a rank the gym added or renamed, a
colour already set. Prajioud arm-bands share a few names (Azul, Verde, Café) but not
the belts, so they are not matched.

The colours are copied here, not imported, so this migration reads the same however
the preset changes.

RLS on `gym` is FORCEd (0001), so the owner running this sees only the gym in
`app.gym_id`; the backfill lifts FORCE for its own transaction and puts it back.

Downgrade drops every rank's `colors`, the gym's own included: the scheme before this
refuses the key, and would read as invalid.

Revision ID: 0026
Revises: 0023
Create Date: 2026-11-10

"""

import json
import unicodedata
from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WHITE, BLACK = "#f4f4f1", "#1b1b1b"
ADULT = {
    "blanca": [WHITE],
    "azul": ["#1f4fa3"],
    "morada": ["#6b2d8f"],
    "cafe": ["#6e4223"],
    "negra": [BLACK],
}
_KIDS = {"gris": "#8b8f94", "amarilla": "#f2c12e", "naranja": "#e8782a", "verde": "#2f8a40"}
KIDS = {
    f"{name}{suffix}": [colour, *tone]
    for name, colour in _KIDS.items()
    for suffix, tone in (("", []), (" y blanca", [WHITE]), (" y negra", [BLACK]))
}
COLOURS = ADULT | KIDS


def _plain(label: str) -> str:
    """`Café ` as `cafe`: lower-case, no accents, single spaces."""
    bare = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return " ".join(bare.lower().split())


def backfill(grading: dict[str, Any]) -> bool:
    """Colours the preset's ranks in `grading`, in place; whether anything changed."""
    ladders = [grading.get(k) or [] for k in ("ranks", "kids_ladder")]
    if not all(isinstance(ladder, list) for ladder in ladders):
        return False
    labels = {_plain(str(r.get("label", ""))) for r in ladders[0] if isinstance(r, dict)}
    if not ADULT.keys() <= labels:
        return False
    changed = False
    for rank in (r for ladder in ladders for r in ladder if isinstance(r, dict)):
        colours = COLOURS.get(_plain(str(rank.get("label", ""))))
        if colours and not rank.get("colors"):
            rank["colors"] = list(colours)
            changed = True
    return changed


def strip(grading: dict[str, Any]) -> bool:
    changed = False
    for ladder in (grading.get(k) or [] for k in ("ranks", "kids_ladder")):
        for rank in ladder if isinstance(ladder, list) else []:
            if isinstance(rank, dict) and "colors" in rank:
                del rank["colors"]
                changed = True
    return changed


def _each_scheme(change: Callable[[dict[str, Any]], bool]) -> None:
    conn = op.get_bind()
    op.execute("ALTER TABLE gym NO FORCE ROW LEVEL SECURITY")
    rows = conn.execute(
        sa.text("SELECT id, settings -> 'grading' AS grading FROM gym WHERE settings ? 'grading'")
    ).all()
    for gym_id, grading in rows:
        scheme = json.loads(grading) if isinstance(grading, str) else grading
        if isinstance(scheme, dict) and change(scheme):
            conn.execute(
                sa.text(
                    "UPDATE gym SET settings = jsonb_set(settings, '{grading}',"
                    " CAST(:grading AS jsonb)) WHERE id = :id"
                ),
                {"grading": json.dumps(scheme), "id": gym_id},
            )
    op.execute("ALTER TABLE gym FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _each_scheme(backfill)


def downgrade() -> None:
    _each_scheme(strip)
