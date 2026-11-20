"""Pruebas unitarias de las métricas en memoria del proceso."""

import pytest

from app.metrics import Metrics

TARGET_MS = 2000
OUTCOMES = ("solved", "escalated", "needs_detail", "incomplete")


def _with_latencies(latencies):
    """Métricas con una petición exitosa por cada latencia."""
    metrics = Metrics()
    for latency in latencies:
        metrics.record_request(status=200, latency_ms=latency)
    return metrics


def _latency(latencies):
    """El p50 y el p95 de esas latencias."""
    return _with_latencies(latencies).snapshot(slo_p95_ms=TARGET_MS)["latency_ms"]


def test_latency_percentiles_use_the_nearest_rank_of_the_last_1000_requests():
    assert _latency([7]) == {"p50": 7, "p95": 7}
    assert _latency([20, 10]) == {"p50": 10, "p95": 20}
    assert _latency(range(100, 0, -1)) == {"p50": 50, "p95": 95}
    many = _with_latencies(range(1, 1101)).snapshot(slo_p95_ms=TARGET_MS)
    assert many["requests"] == 1100
    assert many["latency_ms"] == {"p50": 600, "p95": 1050}


def test_empty_metrics_report_zeros_instead_of_failing():
    snapshot = Metrics().snapshot(slo_p95_ms=TARGET_MS)
    assert snapshot["requests"] == 0
    assert snapshot["error_rate"] == 0
    assert snapshot["latency_ms"] == {"p50": 0, "p95": 0}
    assert snapshot["tokens"] == {"input": 0, "output": 0}
    assert snapshot["outcomes"] == {outcome: 0 for outcome in OUTCOMES}
    assert snapshot["self_service_rate"] == 0


def test_error_and_self_service_rates_come_from_the_recorded_traffic():
    metrics = Metrics()
    for status in (200, 422, 500, 503):
        metrics.record_request(status=status, latency_ms=1)
    for outcome in OUTCOMES:
        metrics.record_answer(outcome=outcome, input_tokens=5, output_tokens=2)
    snapshot = metrics.snapshot(slo_p95_ms=TARGET_MS)
    assert snapshot["error_rate"] == 0.5
    assert snapshot["outcomes"] == {outcome: 1 for outcome in OUTCOMES}
    assert snapshot["self_service_rate"] == 0.25
    assert snapshot["tokens"] == {"input": 20, "output": 8}


def test_the_slo_is_met_only_when_p95_is_below_the_target():
    metrics = _with_latencies([100] * 20)
    below = metrics.snapshot(slo_p95_ms=101)["slo"]
    equal = metrics.snapshot(slo_p95_ms=100)["slo"]
    assert below == {"p95_ms_target": 101, "met": True}
    assert equal == {"p95_ms_target": 100, "met": False}


def test_metrics_add_up_the_cost_and_divide_it_by_the_solved_questions():
    metrics = Metrics()
    empty = metrics.snapshot(slo_p95_ms=TARGET_MS)
    assert (empty["cost_usd"], empty["cost_per_solved_usd"]) == (0, 0)
    metrics.record_answer("escalated", input_tokens=1, output_tokens=1, cost_usd=2e-6)
    unsolved = metrics.snapshot(slo_p95_ms=TARGET_MS)
    assert unsolved["cost_usd"] == pytest.approx(2e-6)
    assert unsolved["cost_usd"] > 0
    assert unsolved["cost_per_solved_usd"] == 0
    metrics.record_answer("solved", input_tokens=1, output_tokens=1, cost_usd=1e-6)
    metrics.record_answer("solved", input_tokens=1, output_tokens=1, cost_usd=3e-6)
    solved = metrics.snapshot(slo_p95_ms=TARGET_MS)
    assert solved["cost_usd"] == pytest.approx(6e-6)
    assert solved["cost_per_solved_usd"] == pytest.approx(3e-6)
