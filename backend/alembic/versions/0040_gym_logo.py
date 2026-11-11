"""A gym's logo (#223).

The owner uploads it in Ajustes, Gimnasio, and it shows wherever the gym is named,
the pages before sign-in among them. Its files live in the blob store under
`logos/<gym_id>/<logo_version>/` (`app.logos`); `gym.logo_version` names the current
set, or is NULL with no logo. A new upload is a new version, so its URLs are new and
can be cached for good.

Like the theme (0039), it is a column, not a key in `gym.settings`, so `rakin_auth`
is granted that one column and `auth_gym_by_slug` returns it beside the name and theme.

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | Sequence[str] | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
AUTH_ROLE = "rakin_auth"

SIGNATURE = "auth_gym_by_slug(text)"

# As 0039 wrote it, with the logo. A function's result type cannot change in place,
# so it is dropped and made again, with 0030's grants and owner.
FUNCTION = """
CREATE FUNCTION auth_gym_by_slug(wanted text)
RETURNS TABLE (id uuid, name text, theme text{logo})
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT g.id, g.name, g.theme{select} FROM public.gym g WHERE g.slug = wanted
$$
"""


def _function(*, logo: bool) -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
    # A new owner needs CREATE on the schema at the moment it takes a function over,
    # and no longer.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {AUTH_ROLE}")
    op.execute(
        FUNCTION.format(
            logo=", logo_version text" if logo else "", select=", g.logo_version" if logo else ""
        )
    )
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO CURRENT_USER")
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO {AUTH_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {AUTH_ROLE}")


def upgrade() -> None:
    # Lower-case hex, as `app.logos.new_version` makes: a path segment as it stands.
    op.execute(
        "ALTER TABLE gym ADD COLUMN logo_version text"
        " CONSTRAINT gym_logo_version_hex CHECK (logo_version ~ '^[0-9a-f]{16,32}$')"
    )
    op.execute(f"GRANT SELECT (logo_version) ON gym TO {AUTH_ROLE}")
    _function(logo=True)


def downgrade() -> None:
    _function(logo=False)
    op.execute(f"REVOKE SELECT (logo_version) ON gym FROM {AUTH_ROLE}")
    op.execute("ALTER TABLE gym DROP COLUMN logo_version")
