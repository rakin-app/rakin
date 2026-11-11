"""A gym's theme: Bosque, Océano or Volcán (#199).

Each gym picks the colours its app wears, in Ajustes, Gimnasio. The pages a person
sees before signing in wear it too (the sign-in screen, the join form, the sign-in
link's pages), so the lookup that finds a host's gym before anyone has signed in,
`auth_gym_by_slug` (0030), returns it beside the name. It is a column, not a key in
`gym.settings`, so `rakin_auth` is granted that one column and never the settings,
which hold the gym's bank details.

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"

# `app.schemas.gym.THEMES`, the first the default.
THEMES = ("bosque", "oceano", "volcan")

SIGNATURE = "auth_gym_by_slug(text)"

# As 0030 wrote it, with the theme. A function's result type cannot change in place,
# so it is dropped and made again, with 0030's grants and owner.
FUNCTION = """
CREATE FUNCTION auth_gym_by_slug(wanted text)
RETURNS TABLE (id uuid, name text{theme})
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT g.id, g.name{select} FROM public.gym g WHERE g.slug = wanted
$$
"""


def _function(*, theme: bool) -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(
        FUNCTION.format(theme=", theme text" if theme else "", select=", g.theme" if theme else "")
    )
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO CURRENT_USER")
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")


def upgrade() -> None:
    allowed = ", ".join(f"'{t}'" for t in THEMES)
    op.execute(
        f"ALTER TABLE gym ADD COLUMN theme text NOT NULL DEFAULT '{THEMES[0]}'"
        f" CONSTRAINT gym_theme_known CHECK (theme IN ({allowed}))"
    )
    op.execute(f"GRANT SELECT (theme) ON gym TO {AUTH_ROLE}")
    _function(theme=True)


def downgrade() -> None:
    _function(theme=False)
    op.execute(f"REVOKE SELECT (theme) ON gym FROM {AUTH_ROLE}")
    op.execute("ALTER TABLE gym DROP COLUMN theme")
