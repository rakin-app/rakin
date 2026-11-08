import pytest

from app.magiclink.ratelimit import MemoryRateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


def test_allows_the_limit_then_says_when_to_retry(clock: Clock) -> None:
    limiter = MemoryRateLimiter(limit=3, window_seconds=60, clock=clock)
    for _ in range(3):
        assert limiter.hit("a") is None
        clock.now += 10

    assert limiter.hit("a") == pytest.approx(30)


def test_the_window_slides(clock: Clock) -> None:
    limiter = MemoryRateLimiter(limit=2, window_seconds=60, clock=clock)
    limiter.hit("a")
    clock.now += 30
    limiter.hit("a")
    assert limiter.hit("a") is not None

    clock.now += 31  # the first hit has left the window
    assert limiter.hit("a") is None
    assert limiter.hit("a") is not None


def test_refused_attempts_do_not_extend_the_wait(clock: Clock) -> None:
    limiter = MemoryRateLimiter(limit=1, window_seconds=60, clock=clock)
    limiter.hit("a")
    for _ in range(10):
        clock.now += 5
        limiter.hit("a")

    clock.now += 11
    assert limiter.hit("a") is None


def test_keys_are_counted_apart(clock: Clock) -> None:
    limiter = MemoryRateLimiter(limit=1, window_seconds=60, clock=clock)
    assert limiter.hit("a") is None
    assert limiter.hit("b") is None
    assert limiter.hit("a") is not None


def test_keys_that_stop_asking_are_forgotten(clock: Clock) -> None:
    limiter = MemoryRateLimiter(limit=1, window_seconds=60, clock=clock)
    for n in range(100):
        limiter.hit(f"k{n}")

    clock.now += 61
    limiter.hit("fresh")

    assert set(limiter._hits) == {"fresh"}


def test_the_limit_must_allow_something() -> None:
    with pytest.raises(ValueError):
        MemoryRateLimiter(limit=0, window_seconds=60)
