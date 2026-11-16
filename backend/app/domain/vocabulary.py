"""What a gym calls itself, its members and its coaches (#344, docs/design/sport-fit.md).

Each word is a key from a short list, never free text: the screens hold each option's
singular, plural and gender (`frontend/src/i18n/vocabulary.ts`), so the copy agrees with
it. The words live in `gym.settings.vocabulary`; a gym with none reads today's,
`DEFAULT`, so the pilot sees no change.

Activities from a preset carry the words a gym of that sport uses (`PRESETS`). A
gym's first activity sets its words, unless the owner has picked them by hand
(`by_hand`); after that nothing changes them on its own.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict

Place = Literal["academia", "club", "gimnasio", "centro", "escuela", "dojo"]
Members = Literal["alumnos", "socios", "deportistas", "miembros"]
Coach = Literal["profe", "sensei", "coach", "entrenador", "instructor", "profesor"]

PLACES: tuple[str, ...] = get_args(Place)
MEMBERS: tuple[str, ...] = get_args(Members)
COACHES: tuple[str, ...] = get_args(Coach)


class Vocabulary(BaseModel):
    """The gym's three words, as every screen reads them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    place: Place
    members: Members
    coach: Coach


# Today's words: a gym that never set any reads exactly as before.
DEFAULT = Vocabulary(place="academia", members="alumnos", coach="profe")
# An activity the gym named itself, with no preset.
NEUTRAL = Vocabulary(place="gimnasio", members="miembros", coach="coach")


@dataclass(frozen=True)
class Preset:
    """An activity Ajustes offers: its name, whether it grades by default, and how gyms
    of that sport in Chile name themselves, their people and the one who teaches."""

    name: str
    uses_grades: bool
    words: Vocabulary


def _words(place: Place, members: Members, coach: Coach) -> Vocabulary:
    return Vocabulary(place=place, members=members, coach=coach)


# By key: stable, stored on the activity (`gym_activity.preset`, 0059), so the activity
# may be renamed. The SPA lists the same keys and names (`ACTIVITY_PRESETS`).
PRESETS: dict[str, Preset] = {
    "bjj": Preset("BJJ", True, _words("academia", "alumnos", "profe")),
    "judo": Preset("Judo", True, _words("dojo", "alumnos", "sensei")),
    "karate": Preset("Karate", True, _words("dojo", "alumnos", "sensei")),
    "taekwondo": Preset("Taekwondo", True, _words("academia", "alumnos", "profe")),
    "muay_thai": Preset("Muay Thai", True, _words("academia", "alumnos", "profe")),
    "boxeo": Preset("Boxeo", False, _words("club", "alumnos", "entrenador")),
    "mma": Preset("MMA", False, _words("academia", "alumnos", "coach")),
    "lucha": Preset("Lucha", False, _words("club", "deportistas", "entrenador")),
    "ballet": Preset("Ballet", False, _words("escuela", "alumnos", "profe")),
    "danza": Preset("Danza", False, _words("escuela", "alumnos", "profe")),
    "musica": Preset("Música", False, _words("escuela", "alumnos", "profesor")),
    "piano": Preset("Piano", False, _words("escuela", "alumnos", "profesor")),
    "escalada": Preset("Escalada", False, _words("gimnasio", "socios", "instructor")),
    "remo": Preset("Remo", False, _words("club", "socios", "entrenador")),
    "natacion": Preset("Natación", False, _words("club", "deportistas", "entrenador")),
    "futbol": Preset("Fútbol", False, _words("escuela", "alumnos", "profe")),
    "crossfit": Preset("Fuerza / CrossFit", False, _words("gimnasio", "socios", "coach")),
    "yoga": Preset("Yoga", False, _words("centro", "alumnos", "profe")),
}

PresetKey = Literal[
    "bjj",
    "judo",
    "karate",
    "taekwondo",
    "muay_thai",
    "boxeo",
    "mma",
    "lucha",
    "ballet",
    "danza",
    "musica",
    "piano",
    "escalada",
    "remo",
    "natacion",
    "futbol",
    "crossfit",
    "yoga",
]


# The activity each graded preset of `app.gyms create --grading` starts the gym with.
GRADING_PRESETS = {"bjj": "bjj", "judo-karate": "judo", "muay-thai": "muay_thai"}


def words_of(preset: str | None) -> Vocabulary:
    """The words an activity of `preset` brings; the neutral ones with none."""
    found = PRESETS.get(preset) if preset is not None else None
    return NEUTRAL if found is None else found.words


def vocabulary_of(settings: Mapping[str, Any] | None) -> Vocabulary:
    """The gym's words in a `gym.settings` document; today's while it has none."""
    return read((settings or {}).get("vocabulary"))


def read(value: object) -> Vocabulary:
    """The words in `gym.settings -> 'vocabulary'` as stored; today's for none."""
    if not isinstance(value, Mapping):
        return DEFAULT
    return Vocabulary.model_validate({k: value[k] for k in ("place", "members", "coach")})


def stored(words: Vocabulary, *, by_hand: bool) -> dict[str, Any]:
    """`words` as `gym.settings.vocabulary` keeps them."""
    return {**words.model_dump(), "by_hand": by_hand}
