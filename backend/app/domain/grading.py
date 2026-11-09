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
    ranks: list[tuple[str, str]], sub_ranks: list[dict[str, str]] | None = None
) -> list[dict[str, Any]]:
    return [{"key": k, "label": label, "sub_ranks": sub_ranks or []} for k, label in ranks]


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

# Kyu count down to 1, then dan count up. Kids climb the same ladder, slower, so there
# is no separate kids ladder.
KYU_DAN = [(f"kyu-{n}", f"{n}.º kyu") for n in range(10, 0, -1)] + [
    (f"dan-{n}", f"{n}.º dan") for n in range(1, 11)
]

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

# In the order the gym is offered them. Boxing and MMA have no grading: `none`.
PRESETS: list[dict[str, Any]] = [
    {
        "key": "bjj",
        "label": "Jiu-jitsu brasileño",
        "scheme": {
            "ranks": _ladder(BJJ_RANKS, STRIPES),
            "kids_ladder": _ladder(BJJ_KIDS_LADDER, STRIPES),
            "goal_metric": "classes_since_promotion",
        },
    },
    {
        "key": "judo-karate",
        "label": "Judo / karate",
        "scheme": {"ranks": _ladder(KYU_DAN), "kids_ladder": [], "goal_metric": "time_in_rank"},
    },
    {
        "key": "muay-thai",
        "label": "Muay thai (prajioud)",
        "scheme": {"ranks": _ladder(PRAJIOUD), "kids_ladder": [], "goal_metric": None},
    },
    {
        "key": "none",
        "label": "Sin grados",
        "scheme": {"ranks": [], "kids_ladder": [], "goal_metric": None},
    },
]
