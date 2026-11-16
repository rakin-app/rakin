"""Sparring only for a gym that spars (#346): the existing gyms brought in line.

Whether a gym spars is `gym.settings.sparring` once its owner picks it, and until then
whether one of its activities comes from a combat sport's preset; a gym with no activity
spars, as today (`app.domain.sparring`). One that does not has its Sparring and Drilling
block kinds (0028's defaults) archived, never deleted, so the time they recorded stays.
A gym that spars calls it by its first combat activity's word: its Sparring kind, while
it is still called so, takes that name ("Randori" in judo). Nothing stores
`gym.settings.sparring`, so the pilot, whose activity is BJJ, sees no change.

The downgrade restores the two kinds and the Sparring name.

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-16

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0061"
down_revision: str | Sequence[str] | None = "0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The combat presets and their words as this migration knows them.
PRACTICES = {
    "bjj": "Sparring",
    "judo": "Randori",
    "karate": "Kumite",
    "taekwondo": "Combate",
    "muay_thai": "Sparring",
    "boxeo": "Sparring",
    "mma": "Sparring",
    "lucha": "Sparring",
}
VALUES = ", ".join(f"('{key}', '{name}')" for key, name in PRACTICES.items())
TABLES = ("gym", "gym_activity", "block_kind")
# The two default kinds of a gym `g` that does not spar.
OFF = f"""
    NOT (g.settings ? 'sparring')
    AND k.id IN (block_kind_default_id(g.id, 'sparring'), block_kind_default_id(g.id, 'drilling'))
    AND EXISTS (SELECT FROM gym_activity a WHERE a.gym_id = g.id)
    AND NOT EXISTS (
        SELECT FROM gym_activity a
        JOIN (VALUES {VALUES}) AS p (key, name) ON p.key = a.preset
        WHERE a.gym_id = g.id)
"""


def _unforced(sql: str) -> None:
    """`sql`, past the policies that hold even the owner to one gym."""
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(sql)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _unforced(f"""
        UPDATE block_kind k SET archived = true
        FROM gym g
        WHERE {OFF}
    """)
    _unforced(f"""
        UPDATE block_kind k SET name = word.name
        FROM gym g
        CROSS JOIN LATERAL (
            SELECT p.name FROM gym_activity a
            JOIN (VALUES {VALUES}) AS p (key, name) ON p.key = a.preset
            WHERE a.gym_id = g.id
            ORDER BY a.created_at, a.id LIMIT 1) AS word
        WHERE k.id = block_kind_default_id(g.id, 'sparring')
          AND k.name = 'Sparring' AND word.name <> 'Sparring'
          AND NOT EXISTS (
              SELECT FROM block_kind o
              WHERE o.gym_id = g.id AND lower(o.name) = lower(word.name))
    """)


def downgrade() -> None:
    names = ", ".join(f"'{name}'" for name in sorted(set(PRACTICES.values()) - {"Sparring"}))
    _unforced(f"""
        UPDATE block_kind k SET archived = false
        FROM gym g
        WHERE {OFF}
    """)
    _unforced(f"""
        UPDATE block_kind k SET name = 'Sparring'
        FROM gym g
        WHERE k.id = block_kind_default_id(g.id, 'sparring') AND k.name IN ({names})
          AND NOT EXISTS (
              SELECT FROM block_kind o WHERE o.gym_id = g.id AND lower(o.name) = 'sparring')
    """)
