"""Whether a gym spars, and what it calls it (#346, docs/design/sport-fit.md).

Sparring is a module: the "Sparring" and "Drilling" block kinds, the "Open mat" class
kind and the sparring totals on a person's training time show only in a gym that spars.
The owner turns it on or off in Ajustes, Bloques (`gym.settings.sparring`); until they
do, a gym spars when one of its activities comes from a combat sport's preset
(`PRACTICES`). A gym with no activity yet reads as today, sparring, as a gym with no
words reads today's (`app.domain.vocabulary`).

The practice has its sport's word: sparring in BJJ, randori in judo, kumite in karate.
The gym's is that of its first activity with one, "sparring" with none.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Literal, get_args

Practice = Literal["sparring", "randori", "kumite", "combate"]

PRACTICE_WORDS: tuple[str, ...] = get_args(Practice)

# The combat sports' presets (`app.domain.vocabulary.PRESETS`), each with its word.
PRACTICES: dict[str, Practice] = {
    "bjj": "sparring",
    "judo": "randori",
    "karate": "kumite",
    "taekwondo": "combate",
    "muay_thai": "sparring",
    "boxeo": "sparring",
    "mma": "sparring",
    "lucha": "sparring",
}

DEFAULT_PRACTICE: Practice = "sparring"

# The default block kinds (0028) the module hides, by the key that derives their id
# (`block_kind_default_id`); the first is the sparring one, named as the practice.
KINDS = ("sparring", "drilling")


def kind_name(practice: Practice) -> str:
    """The sparring block kind's name for a practice: "Sparring", "Randori"."""
    return practice.capitalize()


def spars(settings: Mapping[str, Any] | None, presets: Sequence[str | None]) -> bool:
    """Whether a gym of these settings and these activities' presets spars: the owner's
    pick, else whether any activity is a combat sport's, and with none, yes."""
    stored = (settings or {}).get("sparring")
    if isinstance(stored, bool):
        return stored
    return not presets or any(p in PRACTICES for p in presets)


def practice_of(presets: Sequence[str | None]) -> Practice:
    """The word of the first activity, in the order given, that has one."""
    for preset in presets:
        practice = PRACTICES.get(preset) if preset is not None else None
        if practice is not None:
            return practice
    return DEFAULT_PRACTICE
