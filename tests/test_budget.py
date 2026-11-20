"""Pruebas unitarias del tope de gasto diario de la demo (``app.budget``)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.budget import DailyBudget

LIMIT_USD = 0.5
BEFORE_MIDNIGHT = datetime(2026, 3, 9, 23, 59, 59, tzinfo=timezone.utc)


class ManualClock:
    """Reloj que solo avanza cuando la prueba lo pide."""

    def __init__(self, start=BEFORE_MIDNIGHT):
        self.current = start

    def now(self):
        """Devuelve la hora actual sin avanzarla.

        :return: La hora en UTC.
        :rtype: datetime.datetime
        """
        return self.current


def test_budget_is_exhausted_when_the_spending_reaches_or_passes_the_limit():
    budget = DailyBudget(LIMIT_USD, ManualClock())
    assert budget.is_exhausted() is False
    budget.record(0.25)
    assert budget.is_exhausted() is False
    budget.record(0.25)
    assert budget.is_exhausted() is True
    budget.record(0.125)
    assert budget.is_exhausted() is True


def test_exhaustion_notice_is_claimed_only_once_per_utc_day():
    clock = ManualClock()
    budget = DailyBudget(LIMIT_USD, clock)
    budget.record(LIMIT_USD)
    assert budget.claim_exhaustion_notice() is True
    assert budget.claim_exhaustion_notice() is False
    clock.current += timedelta(seconds=1)
    budget.record(LIMIT_USD)
    assert budget.claim_exhaustion_notice() is True
    assert budget.claim_exhaustion_notice() is False


def test_spending_starts_again_at_utc_midnight():
    clock = ManualClock()
    budget = DailyBudget(LIMIT_USD, clock)
    budget.record(0.75)
    assert budget.is_exhausted() is True
    clock.current += timedelta(seconds=1)
    assert budget.is_exhausted() is False
    assert budget.snapshot()["public_cost_today_usd"] == 0


def test_snapshot_reports_the_spending_of_today_and_the_limit():
    budget = DailyBudget(LIMIT_USD, ManualClock())
    budget.record(0.125)
    budget.record(0.0625)
    snapshot = budget.snapshot()
    assert set(snapshot) == {"public_cost_today_usd", "daily_budget_usd"}
    assert snapshot["public_cost_today_usd"] == pytest.approx(0.1875)
    assert snapshot["daily_budget_usd"] == LIMIT_USD
