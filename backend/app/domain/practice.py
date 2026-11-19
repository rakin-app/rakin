"""A gym's free practice, and what it calls it (#346, docs/design/sport-fit.md).

Every activity has a time its people practise freely: sparring in BJJ, randori in
judo, escalada libre in a climbing gym, nado libre in a pool. It is the block kind the
timer runs in rounds and that a person's training time totals (`is_sparring`, the
default kind 0028 gives every gym), and the open mat is a class made of it alone.

Each activity preset names both (`PRACTICES`): the block, and the open mat when it has
a name of its own ("Open mat" in BJJ; elsewhere the block's). The gym's first activity
that has a preset names its practice; with none yet, or none with a preset, it is the
neutral "Práctica libre", so a new gym does not start as a dojo. The name lands on the
default block kind, which the owner may rename like any other.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Practice:
    """What an activity calls its free practice, and its open mat when that is not the
    same word."""

    block: str
    open_mat: str | None = None


NEUTRAL = Practice("Práctica libre")

# By preset key (`app.domain.vocabulary.PRESETS`), as gyms of each sport in Chile say it.
PRACTICES: dict[str, Practice] = {
    "bjj": Practice("Sparring", "Open mat"),
    "judo": Practice("Randori"),
    "karate": Practice("Kumite"),
    "taekwondo": Practice("Combate"),
    "kenpo": Practice("Sparring"),
    "aikido": Practice("Randori"),
    "muay_thai": Practice("Sparring"),
    "boxeo": Practice("Sparring"),
    "mma": Practice("Sparring", "Open mat"),
    "lucha": Practice("Sparring", "Open mat"),
    "ballet": NEUTRAL,
    "danza": NEUTRAL,
    "musica": NEUTRAL,
    "piano": NEUTRAL,
    "escalada": Practice("Escalada libre"),
    "remo": Practice("Remo libre"),
    "natacion": Practice("Nado libre"),
    "futbol": Practice("Partido"),
    "crossfit": Practice("Open box"),
    "yoga": NEUTRAL,
}

# The default block kind that is the practice, by the key that derives its id
# (`block_kind_default_id`, 0028).
KIND = "sparring"


def practice_of(presets: Sequence[str | None]) -> Practice:
    """The practice of a gym whose activities, oldest first, came from `presets`: the
    first one with a preset names it."""
    for preset in presets:
        if preset is not None:
            return PRACTICES.get(preset, NEUTRAL)
    return NEUTRAL
