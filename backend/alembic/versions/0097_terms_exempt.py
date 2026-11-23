"""The panel says when a gym's terms are current because it is exempt (#559).

`platform_gym` (0094) gains `terms_exempt`: whether `gym_terms.exempt` (0081) marks the
gym, an instance the company does not host. Its terms state was already `current` for
one, and the gym's edit screen, with no acceptance to list, said instead that the
titular had not accepted them yet. Now it says the gym is exempt.

0094's function is rebuilt from its own text, patched by string replacement, as 0094
does. Each patch asserts it matches once.

Revision ID: 0097
Revises: 0096
Create Date: 2026-11-23

"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

from alembic import op

revision: str = "0097"
down_revision: str | Sequence[str] | None = "0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "rakin_app"
PLATFORM_ROLE = "rakin_platform"

GYM = "platform_gym(bytea, uuid, text, text)"


def _migration(name: str) -> ModuleType:
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patched(sql: str, patches: Sequence[tuple[str, str]]) -> str:
    for before, after in patches:
        assert sql.count(before) == 1, before
        sql = sql.replace(before, after)
    return sql


def platform_gym(*, exempt: bool) -> str:
    """0094's `platform_gym`; with `exempt`, whether the gym is exempt from the terms."""
    sql: str = _migration("0094_gym_removal.py").platform_gym(removal=True)
    if not exempt:
        return sql
    return _patched(
        sql,
        [
            (
                "    early_deletion_on date\n)",
                "    early_deletion_on date,\n    terms_exempt boolean\n)",
            ),
            (
                "    g.removal_started_at, g.early_deletion_on\n    FROM public.gym g\n",
                "    g.removal_started_at, g.early_deletion_on,\n"
                "    coalesce((SELECT t.exempt FROM public.gym_terms t"
                " WHERE t.gym_id = g.id), false)\n"
                "    FROM public.gym g\n",
            ),
        ],
    )


def _replace(statement: str) -> None:
    # A new owner needs CREATE on the schema at the moment it takes a function over.
    op.execute(f"GRANT CREATE ON SCHEMA public TO {PLATFORM_ROLE}")
    op.execute(f"DROP FUNCTION {GYM}")
    op.execute(statement)
    op.execute(f"REVOKE ALL ON FUNCTION {GYM} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {GYM} TO {APP_ROLE}")
    op.execute(f"ALTER FUNCTION {GYM} OWNER TO {PLATFORM_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA public FROM {PLATFORM_ROLE}")


def upgrade() -> None:
    _replace(platform_gym(exempt=True))


def downgrade() -> None:
    _replace(platform_gym(exempt=False))
