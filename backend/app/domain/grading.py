"""Grading scheme presets: the spec table's sports, as data.

See docs/technical.md#sport-agnostic-design.

A scheme is an ordered list of ranks, each with optional sub-ranks, an optional
separate kids ladder, and the goal metric a "ready for promotion" flag will read. A
preset is only a starting point: the gym stores its own copy in `gym.settings` and
edits it freely, and nothing in the system branches on which preset it came from.
Promotions reference a rank and a sub-rank by key, so keys are stable ASCII and the
labels are what the gym sees.
"""

from typing import Any


def _ladder(
    ranks: list[tuple[str, str]],
    sub_ranks: list[dict[str, str]] | None = None,
    colors: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    # Each rank its own copies, so editing one rank's sub-ranks never edits another's.
    return [
        {
            "key": k,
            "label": label,
            **({"colors": list(colors[k])} if colors and k in colors else {}),
            "sub_ranks": [dict(s) for s in sub_ranks or []],
        }
        for k, label in ranks
    ]


STRIPES = [
    {"key": "0", "label": "Sin grados"},
    {"key": "1", "label": "1 grado"},
    *({"key": str(n), "label": f"{n} grados"} for n in range(2, 5)),
]

BJJ_RANKS = [
    ("white", "Blanca"),
    ("blue", "Azul"),
    ("purple", "Morada"),
    ("brown", "Café"),
    ("black", "Negra"),
]
# Kids start at white, from the ranks, and move up this ladder until 16.
BJJ_KIDS_LADDER = [
    (f"{colour}{variant}", f"{label}{suffix}")
    for colour, label in (
        ("grey", "Gris"),
        ("yellow", "Amarilla"),
        ("orange", "Naranja"),
        ("green", "Verde"),
    )
    for variant, suffix in (("-white", " y blanca"), ("", ""), ("-black", " y negra"))
]

# A belt's colours by rank key, the second the stripe through a kids' two-tone belt.
_BELT = {
    "white": "#f4f4f1",
    "blue": "#1f4fa3",
    "purple": "#6b2d8f",
    "brown": "#6e4223",
    "black": "#1b1b1b",
    "grey": "#8b8f94",
    "yellow": "#f2c12e",
    "orange": "#e8782a",
    "green": "#2f8a40",
    "red": "#c62f2f",
}
BJJ_COLORS = {key: [_BELT[key]] for key, _ in BJJ_RANKS} | {
    key: [_BELT[base], *([_BELT[tone]] if tone else [])]
    for key, _ in BJJ_KIDS_LADDER
    for base, _, tone in [key.partition("-")]
}


# Kyu count down to 1, then dan count up. Kids climb the same ladder, slower, so there
# is no separate kids ladder. Each art's belts are a common sequence for it (#353,
# #411): federations, countries and schools differ, and the gym edits its own.
def _kyu_dan(
    kyu: list[str], dan: dict[int, list[str]], *, kyu_label: str = "kyu"
) -> tuple[list[tuple[str, str]], dict[str, list[str]]]:
    """A ladder of `len(kyu)` kyu down to 1.º, then `dan`'s degrees, and its belts:
    `kyu` lowest first, each a colour key or a colour and its stripe as `base-tone`."""
    count = len(kyu)
    ranks = [(f"{kyu_label}-{n}", f"{n}.º {kyu_label}") for n in range(count, 0, -1)]
    ranks += [(f"dan-{n}", f"{n}.º dan") for n in dan]
    colors = {
        f"{kyu_label}-{n}": [_BELT[c] for c in belt.split("-")]
        for n, belt in zip(range(count, 0, -1), kyu, strict=True)
    } | {f"dan-{n}": [_BELT[c] for c in colours] for n, colours in dan.items()}
    return ranks, colors


def _black(top: int) -> dict[int, list[str]]:
    return {n: ["black"] for n in range(1, top + 1)}


# Black to 5.º dan, the red and white of 6.º to 8.º and the red of 9.º and 10.º.
_RED_DAN = _black(5) | {n: ["red", "white"] for n in range(6, 9)} | {n: ["red"] for n in (9, 10)}

# Karate, any style (#353): white to brown, then black and the red dan.
KYU_DAN, KYU_DAN_COLORS = _kyu_dan(
    ["white", "yellow", "orange", "green", "blue", "blue", "purple", "brown", "brown", "brown"],
    _RED_DAN,
)
# Judo, Kodokan and IJF: six kyu, white to brown, then black and the red dan.
JUDO, JUDO_COLORS = _kyu_dan(["white", "yellow", "orange", "green", "blue", "brown"], _RED_DAN)
# Shotokan as the JKA grades it: nine kyu, three of them brown, and black to 10.º dan.
SHOTOKAN, SHOTOKAN_COLORS = _kyu_dan(
    ["white", "yellow", "orange", "green", "blue", "purple", "brown", "brown", "brown"],
    _black(10),
)
# Kyokushin as the IKO grades it: each colour twice, the second with the next one's
# stripe, from orange, after the white of a beginner with no kyu (mukyu).
_KYOKUSHIN_KYU = [
    f"{colour}{tone}"
    for colour, after in (
        ("orange", "blue"),
        ("blue", "yellow"),
        ("yellow", "green"),
        ("green", "brown"),
        ("brown", "black"),
    )
    for tone in ("", f"-{after}")
]
KYOKUSHIN, KYOKUSHIN_COLORS = _kyu_dan(_KYOKUSHIN_KYU, _black(10))
KYOKUSHIN.insert(0, ("mukyu", "Mukyu"))
KYOKUSHIN_COLORS["mukyu"] = [_BELT["white"]]
# Goju-ryu: ten kyu, green and blue twice and three of brown, then black to 10.º dan.
GOJU_RYU, GOJU_RYU_COLORS = _kyu_dan(
    ["white", "yellow", "orange", "green", "green", "blue", "blue", "brown", "brown", "brown"],
    _black(10),
)
# Taekwondo as World Taekwondo grades it: ten gup, white to red, each colour followed
# by a step with the next one's stripe, then black to 9.º dan. The poom, a junior's
# black belt, is not here: it is a second ladder for the same grade, not a kids' one.
TAEKWONDO, TAEKWONDO_COLORS = _kyu_dan(
    [
        "white",
        "white-yellow",
        "yellow",
        "yellow-green",
        "green",
        "green-blue",
        "blue",
        "blue-red",
        "red",
        "red-black",
    ],
    _black(9),
    kyu_label="gup",
)
# Aikido as the Aikikai grades it: six kyu in white, then black to 8.º dan.
AIKIDO, AIKIDO_COLORS = _kyu_dan(["white"] * 6, _black(8))

# American Kenpo: white to green, three degrees of brown counting down, then ten of
# black counting up.
KENPO = [
    ("white", "Blanco"),
    ("yellow", "Amarillo"),
    ("orange", "Naranja"),
    ("purple", "Morado"),
    ("blue", "Azul"),
    ("green", "Verde"),
    ("brown-3", "Café 3.er grado"),
    ("brown-2", "Café 2.º grado"),
    ("brown-1", "Café 1.er grado"),
    ("black-1", "Negro 1.er grado"),
    *((f"black-{n}", f"Negro {n}.º grado") for n in range(2, 11)),
]
KENPO_COLORS = {key: [_BELT[key.partition("-")[0]]] for key, _ in KENPO}

# Prajioud arm-band colours. Camps and federations order them differently; this is a
# common sequence, for the gym to edit.
PRAJIOUD = [
    ("white", "Blanco"),
    ("yellow", "Amarillo"),
    ("orange", "Naranjo"),
    ("green", "Verde"),
    ("blue", "Azul"),
    ("red", "Rojo"),
    ("brown", "Café"),
    ("black", "Negro"),
]
# Each arm band its colour (#353), so the scheme reads as bands, not levels.
PRAJIOUD_COLORS = {key: [_BELT[key]] for key, _ in PRAJIOUD}

# In the order the gym is offered them, each art's styles together. Boxing and MMA have
# no grading: `none`.
PRESETS: list[dict[str, Any]] = [
    {
        "key": "bjj",
        "label": "Jiu-jitsu brasileño",
        "scheme": {
            "ranks": _ladder(BJJ_RANKS, STRIPES, BJJ_COLORS),
            "kids_ladder": _ladder(BJJ_KIDS_LADDER, STRIPES, BJJ_COLORS),
            "goal_metric": "classes_since_promotion",
        },
    },
    {
        "key": "judo",
        "label": "Judo",
        "scheme": {
            "ranks": _ladder(JUDO, colors=JUDO_COLORS),
            "kids_ladder": [],
            "goal_metric": "time_in_rank",
        },
    },
    {
        "key": "karate",
        "label": "Karate (otros estilos)",
        "scheme": {
            "ranks": _ladder(KYU_DAN, colors=KYU_DAN_COLORS),
            "kids_ladder": [],
            "goal_metric": "time_in_rank",
        },
    },
    {
        "key": "karate-shotokan",
        "label": "Karate Shotokan (JKA)",
        "scheme": {
            "ranks": _ladder(SHOTOKAN, colors=SHOTOKAN_COLORS),
            "kids_ladder": [],
            "goal_metric": "time_in_rank",
        },
    },
    {
        "key": "karate-kyokushin",
        "label": "Karate Kyokushin (IKO)",
        "scheme": {
            "ranks": _ladder(KYOKUSHIN, colors=KYOKUSHIN_COLORS),
            "kids_ladder": [],
            "goal_metric": "time_in_rank",
        },
    },
    {
        "key": "karate-goju-ryu",
        "label": "Karate Goju-ryu",
        "scheme": {
            "ranks": _ladder(GOJU_RYU, colors=GOJU_RYU_COLORS),
            "kids_ladder": [],
            "goal_metric": "time_in_rank",
        },
    },
    {
        "key": "taekwondo",
        "label": "Taekwondo (WT)",
        "scheme": {
            "ranks": _ladder(TAEKWONDO, colors=TAEKWONDO_COLORS),
            "kids_ladder": [],
            "goal_metric": "time_in_rank",
        },
    },
    {
        "key": "kenpo",
        "label": "Kenpo americano",
        "scheme": {
            "ranks": _ladder(KENPO, colors=KENPO_COLORS),
            "kids_ladder": [],
            "goal_metric": "time_in_rank",
        },
    },
    {
        "key": "aikido",
        "label": "Aikido (Aikikai)",
        "scheme": {
            "ranks": _ladder(AIKIDO, colors=AIKIDO_COLORS),
            "kids_ladder": [],
            "goal_metric": "time_in_rank",
        },
    },
    {
        "key": "muay-thai",
        "label": "Muay thai (prajioud)",
        "scheme": {
            "ranks": _ladder(PRAJIOUD, colors=PRAJIOUD_COLORS),
            "kids_ladder": [],
            "goal_metric": None,
        },
    },
    # Levels (#353): a swimming school's or a climbing gym's, no colours and no
    # sub-ranks, for the gym to fill.
    {
        "key": "levels",
        "label": "Niveles",
        "scheme": {"ranks": [], "kids_ladder": [], "goal_metric": None},
    },
    {
        "key": "none",
        "label": "Sin grados",
        "scheme": {"ranks": [], "kids_ladder": [], "goal_metric": None},
    },
]

# Keys a preset once had, to the one it is now, so `app.gyms create --grading` and the
# panel still take them. `judo-karate` (#411) was one ladder for both; it starts a judo
# gym, as it always did.
ALIASES = {"judo-karate": "judo"}


def resolve(key: str) -> str:
    """The preset `key` names now: itself, or the one an old key became."""
    return ALIASES.get(key, key)
