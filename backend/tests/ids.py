"""Made-up identities for tests: a RUT, an email, a phone no other test in the run holds.
A person is their RUT, or an email in one gym (migration 0036), so most tests that add
someone need one of the two.

Each comes off one sequence for the whole run, not a random draw: a full run makes
thousands of people, and random RUTs then meet (birthday odds), which `person_rut_key`
refuses. Every module's own helper draws from here too, so two modules never hand out
the same one. Each sequence starts at a per-run random point in its own slice, one per
xdist worker if the run is split, and the RUTs stay clear of the demo seed's (8M to
26M) and of the RUTs tests write by hand (under 25M, and the 76M of companies).
"""

import itertools
import os
import random
import re
import uuid

from app.domain.rut import check_digit

# Room for every person one run makes, with a wide margin.
PER_RUN = 1_000_000
# This process's worker, `gw3`, or none outside xdist.
_WORKER = int(re.sub(r"\D", "", os.environ.get("PYTEST_XDIST_WORKER", "")) or 0)
# The slices below hold nine: a tenth's RUTs would reach the 76M of companies, and its
# phones a ninth digit.
MAX_WORKERS = 9
assert _WORKER < MAX_WORKERS, (
    f"tests/ids.py has identity slices for {MAX_WORKERS} xdist workers (gw0 to gw8),"
    f" not gw{_WORKER}: run with -n {MAX_WORKERS} or fewer, or make the slices smaller"
)


def _sequence(floor: int, slice_size: int) -> "itertools.count[int]":
    """Numbers from a random start in this worker's slice of `slice_size` from `floor`,
    one run's worth of them always inside it."""
    start = floor + _WORKER * slice_size + random.randrange(slice_size - PER_RUN)
    return itertools.count(start)


# RUT bodies 30M to 75M: `MAX_WORKERS` slices of 5M.
_ruts = _sequence(30_000_000, 5_000_000)
# The eight digits after +569: `MAX_WORKERS` slices of 10M from 10M.
_phones = _sequence(10_000_000, 10_000_000)
_emails = itertools.count()
# Apart from another run's addresses in a database a run reuses.
_RUN = uuid.uuid4().hex[:6]


def random_rut() -> str:
    """A valid RUT in the stored form (`12345678-5`), unused in this run."""
    body = next(_ruts)
    return f"{body}-{check_digit(body)}"


def random_email() -> str:
    return f"p{_RUN}{next(_emails)}@example.com"


def random_phone() -> str:
    return f"+569{next(_phones):08d}"
