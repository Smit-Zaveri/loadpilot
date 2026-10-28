import math
import random

import pytest

from loadpilot.metrics import Histogram, MetricsCollector, RunAggregator


def _exact_percentile(values, p):
    s = sorted(values)
    return s[max(1, math.ceil(p / 100 * len(s))) - 1]


def test_histogram_percentiles_within_one_percent():
    rng = random.Random(42)
    values = [rng.lognormvariate(3, 1) for _ in range(20_000)]
    h = Histogram()
    for v in values:
        h.record(v)
    for p in (50, 90, 95, 99, 99.9):
        assert h.percentile(p) == pytest.approx(_exact_percentile(values, p), rel=0.011)
    assert h.max == max(values)
    assert h.percentile(100) == max(values)
    assert h.mean == pytest.approx(sum(values) / len(values))


def test_histogram_merge_equals_combined_and_roundtrips():
    a, b, both = Histogram(), Histogram(), Histogram()
    for i in range(1, 500):
        a.record(i)
        both.record(i)
    for i in range(400, 2000):
        b.record(i * 1.5)
        both.record(i * 1.5)
    a.merge(Histogram.from_dict(b.to_dict()))
    assert a.summary() == both.summary()


def test_empty_histogram_summary_is_zero():
    h = Histogram.from_dict(Histogram().to_dict())
    assert h.summary() == {k: 0.0 for k in ("min", "mean", "p50", "p90", "p95", "p99", "max")}


def test_collector_counts_failures():
    c = MetricsCollector()
    c.record("s", latency_ms=5, service_ms=5, status=200, bytes_in=3)
    c.record("s", latency_ms=5, service_ms=5, status=503)
    c.record("s", latency_ms=5, service_ms=5, status=None, error="timeout", error_detail="slow")
    c.record_dropped()
    data = c.flush()
    s = data["steps"]["s"]
    assert (s["requests"], s["failed"], s["bytes_in"], data["dropped"]) == (3, 2, 3, 1)
    assert s["status"] == {"200": 1, "503": 1}
    assert s["errors"] == {"timeout": 1}
    assert s["error_samples"] == {"timeout": "slow"}
    assert c.flush() == {"steps": {}, "dropped": 0}


def _tick(t, start, window, n, final=False):
    c = MetricsCollector()
    for _ in range(n):
        c.record("s", latency_ms=10, service_ms=10, status=200)
    return {
        "t": t,
        "start": start,
        "window": window,
        "final": final,
        "target": 1,
        "active_vus": 1,
        "in_flight": 0,
        "loop_lag_ms": 0,
        "events": [],
        **c.flush(),
    }


def test_aggregator_excludes_warmup_and_short_final_tick():
    agg = RunAggregator(warmup=1.0)
    agg.add_tick(_tick(0, 0.0, 1.0, 100))  # warm-up
    p = agg.add_tick(_tick(1, 1.0, 1.0, 50))
    assert p["overall"]["rps"] == 50
    assert agg.add_tick(_tick(2, 2.0, 0.1, 5, final=True)) is None
    s = agg.summary()
    assert len(agg.series) == 2
    assert s["requests"] == 55
    assert s["duration"] == pytest.approx(1.1)
    assert s["latency"]["p50"] == pytest.approx(10, rel=0.011)
