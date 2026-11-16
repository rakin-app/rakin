"""Which preset an activity came from (#344): `gym_activity.preset`.

Ajustes offers activities from presets ("BJJ", "Judo", "Escalada"), and each preset
names what a gym of that sport calls itself, its members and its coach
(`app.domain.vocabulary`); #346 keys the practice word off it too. The name can be
changed afterwards, so the preset is stored apart, as its key: `bjj`, `muay_thai`.
NULL is an activity the gym named itself.

An activity already stored whose name is a preset's, case ignored, gets that preset's
key. Nothing writes `gym.settings.vocabulary`: a gym with none reads today's words, so
the pilot's screens do not change.

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-16

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0059"
down_revision: str | Sequence[str] | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The presets as this migration knows them, key and name; later ones do not matter here.
PRESETS = {
    "bjj": "BJJ",
    "judo": "Judo",
    "karate": "Karate",
    "taekwondo": "Taekwondo",
    "muay_thai": "Muay Thai",
    "boxeo": "Boxeo",
    "mma": "MMA",
    "lucha": "Lucha",
    "ballet": "Ballet",
    "danza": "Danza",
    "musica": "Música",
    "piano": "Piano",
    "escalada": "Escalada",
    "remo": "Remo",
    "natacion": "Natación",
    "futbol": "Fútbol",
    "crossfit": "Fuerza / CrossFit",
    "yoga": "Yoga",
}


def upgrade() -> None:
    # A key as the app writes them: lower-case words joined by underscores.
    op.execute(
        "ALTER TABLE gym_activity ADD COLUMN preset text"
        " CONSTRAINT gym_activity_preset_key CHECK (preset ~ '^[a-z]+(_[a-z]+)*$')"
    )
    values = ", ".join(f"('{key}', '{name}')" for key, name in PRESETS.items())
    # Past the policy that holds even the owner to one gym, and back under it.
    op.execute("ALTER TABLE gym_activity NO FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        UPDATE gym_activity a SET preset = p.key
        FROM (VALUES {values}) AS p (key, name)
        WHERE lower(a.name) = lower(p.name)
    """)
    op.execute("ALTER TABLE gym_activity FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE gym_activity DROP COLUMN preset")
