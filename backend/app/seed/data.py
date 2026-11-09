"""Academia Sur, the demo gym: its programs, class types, plans, grading scheme, staff and
members.

This is the data, not the rows: `app.seed.build` turns it into rows for a given seed
date. The members the UI design names (`docs/design/ui-design.html`) are written out
with the standing the design shows them in, relative to the seed date, so the design's
"today" (Saturday 8 November 2026) is any day the seed is loaded on. The rest of the
roster is filler drawn from a fixed random sequence, so every load is the same gym.

Belts have no table yet (#48): ranks live here, checked against the grading scheme.
Each kid names the member who pays for them (`MemberSpec.guardian`), which becomes
their `guardian_link` row and the payer of their ledger entries. In this gym every
guardian trains too.
"""

import copy
import random
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.domain import grading
from app.domain.billing import GENERATE_AHEAD_DAYS
from app.domain.membership import MembershipStatus, PlanKind
from app.roles import Role

GYM_NAME = "Academia Sur"
GYM_SLUG = "academia-sur"
TIMEZONE = "America/Santiago"
# Felipe Díaz is 9 days overdue in the design and still Active.
GRACE_DAYS = 10
# How far back a member's paid history goes, in billing periods.
HISTORY_PERIODS = 6


# The gym's programs (migration 0016), by key.
PROGRAMS = {"adults": "Adultos", "kids": "Kids", "competition": "Competición"}


@dataclass(frozen=True)
class ClassTypeSpec:
    key: str
    program: str
    name: str
    credit_cost: int = 1


CLASS_TYPES = (
    ClassTypeSpec("fundamentals", "adults", "Fundamentos"),
    ClassTypeSpec("advanced", "adults", "Avanzado"),
    ClassTypeSpec("open-mat", "adults", "Open mat", credit_cost=0),
    ClassTypeSpec("kids-little", "kids", "Kids 4 a 7 años"),
    ClassTypeSpec("kids-big", "kids", "Kids 8 a 12 años"),
    ClassTypeSpec("competition", "competition", "Competición"),
)


@dataclass(frozen=True)
class PlanSpec:
    key: str
    name: str
    kind: PlanKind
    price_clp: int
    # The program its members are in; none for a plan open to any class.
    program: str | None = None
    # Monthly plans bill on the member's signup day of the month (migration 0007).
    anchor: str | None = None
    period_months: int | None = None
    # Classes in a pack; free classes on a trial.
    credits: int | None = None
    # Days a pack lasts; free days on a trial.
    credit_expiry_days: int | None = None


PLANS = (
    PlanSpec("adults", "Mensual adultos", PlanKind.MONTHLY, 45_000, "adults", anchor="signup"),
    PlanSpec(
        "competition",
        "Mensual competición",
        PlanKind.MONTHLY,
        60_000,
        "competition",
        anchor="signup",
    ),
    PlanSpec("student", "Estudiante", PlanKind.MONTHLY, 30_000, "adults", anchor="signup"),
    PlanSpec("kids", "Mensual kids", PlanKind.MONTHLY, 36_000, "kids", anchor="signup"),
    PlanSpec("prepaid-6", "Prepago 6 meses", PlanKind.PREPAID, 240_000, "adults", period_months=6),
    PlanSpec(
        "pack-12", "Pack 12 clases", PlanKind.CREDITS, 45_000, credits=12, credit_expiry_days=60
    ),
    PlanSpec("dropin", "Clase suelta", PlanKind.DROPIN, 10_000),
    PlanSpec("trial", "Clase de prueba", PlanKind.TRIAL, 0, credits=2, credit_expiry_days=14),
)

# A copy of the BJJ preset as it comes, so a change here never reaches the preset that
# `/api/gym/grading-scheme/presets` serves. Kids start at white, from `RANKS`, and move
# up the ladder.
GRADING: dict[str, Any] = copy.deepcopy(
    next(p["scheme"] for p in grading.PRESETS if p["key"] == "bjj")
)
RANKS = grading.BJJ_RANKS
KIDS_LADDER = grading.BJJ_KIDS_LADDER
STRIPES = len(grading.STRIPES) - 1

CUSTOM_FIELDS = [
    {"key": "emergency_contact", "label": "Contacto de emergencia", "type": "text"},
    {
        "key": "weight_class",
        "label": "Categoría competencia",
        "type": "enum",
        "options": ["Gallo", "Pluma", "Pena", "Leve", "Medio", "Meio-pesado", "Pesado"],
    },
    {"key": "medical_notes", "label": "Notas médicas", "type": "text", "sensitive": True},
]

BANK_ACCOUNT = {
    "bank": "Banco Estado",
    "account_type": "Cuenta Vista",
    "holder": "Academia Sur SpA",
    "rut": "76432109-K",
    "number": "000012348821",
    "email": "pagos@academiasur.example.com",
}


@dataclass(frozen=True)
class StaffSpec:
    key: str
    name: str
    role: Role


STAFF = (
    StaffSpec("martin", "Martín Fuentes", Role.OWNER),
    StaffSpec("carolina", "Carolina Lagos", Role.ADMIN),
    StaffSpec("sebastian", "Sebastián Araya", Role.COACH),
)
# Who validates payments and records cash.
VALIDATOR = "martin"


class Standing(StrEnum):
    # Nothing that has fallen due is unpaid.
    PAID = "paid"
    # The latest billing period is past due with no payment.
    OVERDUE = "overdue"
    # A proof for the latest billing period is waiting for validation.
    PENDING = "pending"


class Method(StrEnum):
    TRANSFER = "transfer"
    CASH = "cash"


S = MembershipStatus


@dataclass(frozen=True)
class MemberSpec:
    key: str
    name: str
    plan: str
    # Rank key from `GRADING` and stripes.
    rank: tuple[str, int]
    standing: Standing = Standing.PAID
    # Days from the seed date to the day that anchors the member's billing (negative is
    # past): the latest period's due date on a monthly plan, the next block's due date on
    # a prepaid one, the day the pack was bought or the trial started otherwise.
    due_in: int = 0
    status: MembershipStatus = S.ACTIVE
    # Months the membership ran before the latest period.
    since_months: int = 12
    # The key of the member who pays for this one.
    guardian: str | None = None
    method: Method = Method.TRANSFER
    # When the latest period was paid or its proof sent: (days from the seed date, hour,
    # minute), gym-local. Default: a day near the due date.
    at: tuple[int, int, int] | None = None
    overpaid_clp: int = 0
    credits_remaining: int | None = None
    discount_pct: int = 0
    phone: str | None = None

    @property
    def is_kid(self) -> bool:
        return self.plan == "kids"


# The people the design screens show, as they stand there.
NAMED = (
    MemberSpec(
        "felipe-diaz",
        "Felipe Díaz",
        "adults",
        ("blue", 2),
        Standing.OVERDUE,
        due_in=-9,
        since_months=32,
        phone="+56998214417",
    ),
    MemberSpec("javiera-silva", "Javiera Silva", "adults", ("white", 3), Standing.OVERDUE, -4),
    MemberSpec("tomas-perez", "Tomás Pérez", "student", ("white", 0), Standing.OVERDUE, -2),
    MemberSpec(
        "matias-gonzalez", "Matías González", "competition", ("purple", 2), Standing.OVERDUE, -7
    ),
    MemberSpec("constanza-munoz", "Constanza Muñoz", "adults", ("blue", 1), Standing.OVERDUE, -6),
    MemberSpec("benjamin-rojas", "Benjamín Rojas", "adults", ("white", 2), Standing.OVERDUE, -4),
    MemberSpec(
        "diego-morales",
        "Diego Morales",
        "adults",
        ("purple", 1),
        Standing.PENDING,
        due_in=2,
        since_months=40,
        at=(0, 14, 12),
    ),
    MemberSpec(
        "catalina-reyes",
        "Catalina Reyes",
        "adults",
        ("blue", 3),
        Standing.PENDING,
        5,
        at=(-1, 8, 30),
    ),
    MemberSpec("camila-ortiz", "Camila Ortiz", "adults", ("blue", 0), due_in=-18),
    MemberSpec(
        "mateo-ortiz",
        "Mateo Ortiz",
        "kids",
        ("grey", 1),
        Standing.PENDING,
        due_in=2,
        guardian="camila-ortiz",
        at=(-1, 19, 40),
    ),
    MemberSpec(
        "sofia-ortiz",
        "Sofía Ortiz",
        "kids",
        ("grey-white", 2),
        Standing.PENDING,
        due_in=2,
        status=S.FROZEN,
        guardian="camila-ortiz",
        at=(-1, 19, 40),
    ),
    MemberSpec(
        "valentina-soto",
        "Valentina Soto",
        "adults",
        ("blue", 0),
        due_in=-1,
        method=Method.CASH,
        at=(-1, 9, 5),
    ),
    MemberSpec(
        "andres-molina", "Andrés Molina", "prepaid-6", ("brown", 0), due_in=5, since_months=30
    ),
    MemberSpec(
        "paula-contreras",
        "Paula Contreras",
        "pack-12",
        ("blue", 0),
        due_in=-4,
        at=(-4, 20, 1),
        overpaid_clp=5_000,
        credits_remaining=4,
    ),
    MemberSpec("ignacio-vera", "Ignacio Vera", "adults", ("white", 1), due_in=-12),
    MemberSpec("antonia-rojas", "Antonia Rojas", "adults", ("blue", 0), due_in=-15),
    MemberSpec(
        "cristobal-herrera",
        "Cristóbal Herrera",
        "adults",
        ("purple", 0),
        due_in=-10,
        status=S.FROZEN,
    ),
)

FIRST_NAMES = (  # noqa: SIM905 - a word list reads better than one name per line
    "Agustín Alonso Bastián Carlos Cristián Daniel Eduardo Emilio Felipe Francisco "
    "Gabriel Gonzalo Joaquín José Juan Lucas Luis Manuel Martín Maximiliano Nicolás "
    "Pablo Rafael Ricardo Rodrigo Sebastián Vicente Alejandra Amanda Antonella Bárbara "
    "Belén Carolina Daniela Fernanda Florencia Francisca Ignacia Isidora Josefa Karina "
    "Lorena Martina Natalia Pía Rocío Trinidad Valeria Ximena"
).split()
KID_NAMES = (  # noqa: SIM905 - a word list reads better than one name per line
    "Agustina Benjamín Clemente Emilia Gaspar Julieta Florencia León Maite Renato Simón "
    "Amparo Facundo Laura Pedro"
).split()
SURNAMES = (  # noqa: SIM905 - a word list reads better than one name per line
    "Araya Bravo Cáceres Carrasco Castillo Cortés Figueroa Flores Fuentes Gómez "
    "Gutiérrez Hernández Jara López Martínez Medina Mora Núñez Olivares Pizarro Ramírez "
    "Riquelme Saavedra Sandoval Sepúlveda Tapia Torres Valenzuela Vargas Vásquez Zúñiga"
).split()


def slug(name: str) -> str:
    """`Martín Saavedra` -> `martin-saavedra`."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return folded.lower().replace(" ", "-")


def _filler() -> tuple[MemberSpec, ...]:
    """The rest of the roster: the same members on every call."""
    rng = random.Random(GYM_SLUG)
    taken = {p.name for p in (*NAMED, *STAFF)}
    members: list[MemberSpec] = []

    def name(first_names: Sequence[str], surname: str | None = None) -> str:
        while True:
            full = f"{rng.choice(first_names)} {surname or rng.choice(SURNAMES)}"
            if full not in taken:
                taken.add(full)
                return full

    def paid_due_in() -> int:
        # Recent enough that the next period is not generated yet.
        return rng.randrange(-20, GENERATE_AHEAD_DAYS + 1)

    def adult(
        plan: str,
        *,
        due_in: int | None = None,
        standing: Standing = Standing.PAID,
        status: MembershipStatus = S.ACTIVE,
        since_months: int | None = None,
        credits_remaining: int | None = None,
    ) -> None:
        full = name(FIRST_NAMES)
        belt = rng.choices([k for k, _ in RANKS], [8, 6, 3, 2, 1])[0]
        members.append(
            MemberSpec(
                slug(full),
                full,
                plan,
                (belt, rng.randrange(STRIPES + 1)),
                standing,
                due_in=paid_due_in() if due_in is None else due_in,
                status=status,
                since_months=rng.randrange(1, 48) if since_months is None else since_months,
                method=Method.CASH if rng.random() < 0.2 else Method.TRANSFER,
                credits_remaining=credits_remaining,
            )
        )

    for _ in range(25):
        adult("adults")
    for _ in range(5):
        adult("student")
    for _ in range(3):
        adult("competition")
    for due_in in (40, 95):
        adult("prepaid-6", due_in=due_in)
    for due_in, left in ((-21, 7), (-48, 2)):
        adult("pack-12", due_in=due_in, credits_remaining=left)
    for due_in, left in ((-3, 1), (-1, 2)):
        adult("trial", due_in=due_in, status=S.TRIAL, since_months=0, credits_remaining=left)
    for due_in in (-25, -34):
        adult("adults", standing=Standing.OVERDUE, due_in=due_in, status=S.LAPSED)
    adult("adults", due_in=-62, status=S.CANCELLED)

    # Kids, by family: (adult member who pays, number of kids).
    families = [
        (members[i].key, n) for i, n in ((0, 2), (3, 2), (7, 1), (12, 2), (15, 2), (18, 2), (21, 1))
    ]
    surnames = {m.key: m.name.split()[-1] for m in members}
    kid_belts = ["white", *(k for k, _ in KIDS_LADDER[:6])]
    for guardian, count in families:
        # Siblings are billed together.
        due_in = paid_due_in()
        for _ in range(count):
            full = name(KID_NAMES, surnames[guardian])
            members.append(
                MemberSpec(
                    slug(full),
                    full,
                    "kids",
                    (rng.choice(kid_belts), rng.randrange(STRIPES + 1)),
                    due_in=due_in,
                    since_months=rng.randrange(2, 30),
                    guardian=guardian,
                    # One scholarship.
                    discount_pct=50 if guardian == families[-1][0] else 0,
                )
            )
    return tuple(members)


MEMBERS: tuple[MemberSpec, ...] = (*NAMED, *_filler())
