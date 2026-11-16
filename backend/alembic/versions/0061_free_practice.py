"""A gym's free practice under its activity's name (#346): the existing gyms.

Every gym's default "Sparring" block kind (0028) is its free practice, and its first
activity now names it (`app.domain.practice`): Randori in judo, Escalada libre in a
climbing gym, "Práctica libre" for an activity with no preset or a gym with none yet.
A kind still called "Sparring" takes that name, unless another of the gym's kinds has
it already. One the gym renamed keeps its name, and the pilot, whose activity is BJJ,
keeps "Sparring".

The downgrade gives "Sparring" back to every kind called one of the names below.

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

NEUTRAL = "Práctica libre"
# The presets' names for it as this migration knows them; any other preset, or none,
# is NEUTRAL.
PRACTICES = {
    "bjj": "Sparring",
    "judo": "Randori",
    "karate": "Kumite",
    "taekwondo": "Combate",
    "muay_thai": "Sparring",
    "boxeo": "Sparring",
    "mma": "Sparring",
    "lucha": "Sparring",
    "escalada": "Escalada libre",
    "remo": "Remo libre",
    "natacion": "Nado libre",
    "futbol": "Partido",
    "crossfit": "Open box",
}
VALUES = ", ".join(f"('{key}', '{name}')" for key, name in PRACTICES.items())
TABLES = ("gym", "gym_activity", "block_kind")


def _unforced(sql: str) -> None:
    """`sql`, past the policies that hold even the owner to one gym."""
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(sql)
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _unforced(f"""
        UPDATE block_kind k SET name = word.name
        FROM gym g
        CROSS JOIN LATERAL (
            SELECT coalesce(
                (SELECT p.name FROM gym_activity a
                 LEFT JOIN (VALUES {VALUES}) AS p (key, name) ON p.key = a.preset
                 WHERE a.gym_id = g.id
                 ORDER BY a.created_at, a.id LIMIT 1),
                '{NEUTRAL}') AS name) AS word
        WHERE k.id = block_kind_default_id(g.id, 'sparring')
          AND k.name = 'Sparring' AND word.name <> 'Sparring'
          AND NOT EXISTS (
              SELECT FROM block_kind o
              WHERE o.gym_id = g.id AND lower(o.name) = lower(word.name))
    """)


def downgrade() -> None:
    # Every name the upgrade may have written goes back to "Sparring": nothing records
    # which kinds it renamed, and a gym that named its own kind one of these loses that
    # name too, the price of a downgrade with no record to read.
    names = sorted((set(PRACTICES.values()) | {NEUTRAL}) - {"Sparring"})
    listed = ", ".join(f"'{name}'" for name in names)
    _unforced(f"""
        UPDATE block_kind k SET name = 'Sparring'
        FROM gym g
        WHERE k.id = block_kind_default_id(g.id, 'sparring') AND k.name IN ({listed})
          AND NOT EXISTS (
              SELECT FROM block_kind o WHERE o.gym_id = g.id AND lower(o.name) = 'sparring')
    """)
