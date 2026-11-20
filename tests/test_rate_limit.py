"""Pruebas unitarias del límite de peticiones por cliente con un reloj manual."""

from datetime import datetime, timedelta, timezone

from app.rate_limit import RateLimiter

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class ManualClock:
    """Reloj que solo avanza cuando la prueba lo pide."""

    def __init__(self):
        self.current = START

    def now(self):
        """Devuelve la hora actual sin avanzarla.

        :return: La hora en UTC.
        :rtype: datetime.datetime
        """
        return self.current

    def advance(self, seconds):
        """Adelanta el reloj.

        :param seconds: Segundos que avanza.
        :type seconds: float
        """
        self.current += timedelta(seconds=seconds)


def test_limit_allows_exactly_the_configured_requests_per_client():
    limiter = RateLimiter(2, ManualClock())
    assert limiter.check("alpha") is None
    assert limiter.check("alpha") is None
    assert limiter.check("alpha") is not None
    assert limiter.check("beta") is None
    assert limiter.check("beta") is None


def test_retry_after_is_rounded_up_and_at_least_one_second():
    clock = ManualClock()
    limiter = RateLimiter(2, clock)
    limiter.check("alpha")
    clock.advance(0.5)
    limiter.check("alpha")
    clock.advance(0.75)
    assert limiter.check("alpha") == 59
    clock.advance(58.249)
    assert limiter.check("alpha") == 1


def test_window_is_released_after_sixty_seconds():
    clock = ManualClock()
    limiter = RateLimiter(1, clock)
    assert limiter.check("alpha") is None
    clock.advance(59.5)
    assert limiter.check("alpha") == 1
    clock.advance(0.5)
    assert limiter.check("alpha") is None
    assert limiter.check("alpha") == 60


def test_inactive_keys_are_purged_without_changing_the_answers():
    clock = ManualClock()
    limiter = RateLimiter(1, clock)
    assert limiter.check("203.0.113.1") is None
    clock.advance(30)
    assert limiter.check("203.0.113.2") is None
    clock.advance(31)
    assert limiter.check("203.0.113.3") is None
    assert limiter.tracked_keys() == 2
    assert limiter.check("203.0.113.2") == 29
    assert limiter.check("203.0.113.1") is None
