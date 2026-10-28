from __future__ import annotations

from collections import Counter
from typing import Any

from .histogram import Histogram

# Final ticks shorter than this are folded into the summary but not charted,
# because rates computed over a tiny window are misleading.
_MIN_CHART_WINDOW = 0.5


class _Totals:
    def __init__(self) -> None:
        self.requests = 0
        self.failed = 0
        self.status: Counter[str] = Counter()
        self.errors: Counter[str] = Counter()
        self.error_samples: dict[str, str] = {}
        self.bytes_in = 0
        self.latency = Histogram()
        self.service = Histogram()

    def add_step(self, d: dict[str, Any]) -> None:
        self.requests += d["requests"]
        self.failed += d["failed"]
        self.status.update(d["status"])
        self.errors.update(d["errors"])
        for k, v in d["error_samples"].items():
            self.error_samples.setdefault(k, v)
        self.bytes_in += d["bytes_in"]
        self.latency.merge(Histogram.from_dict(d["latency"]))
        self.service.merge(Histogram.from_dict(d["service"]))

    def merge(self, other: _Totals) -> None:
        self.requests += other.requests
        self.failed += other.failed
        self.status.update(other.status)
        self.errors.update(other.errors)
        for k, v in other.error_samples.items():
            self.error_samples.setdefault(k, v)
        self.bytes_in += other.bytes_in
        self.latency.merge(other.latency)
        self.service.merge(other.service)

    def point(self, window: float) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "failed": self.failed,
            "rps": round(self.requests / window, 3) if window > 0 else 0.0,
            "error_rate": round(self.failed / self.requests, 5) if self.requests else 0.0,
            "status": dict(self.status),
            **self.latency.summary(),
        }

    def summary(self, duration: float) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "failed": self.failed,
            "error_rate": round(self.failed / self.requests, 5) if self.requests else 0.0,
            "rps": round(self.requests / duration, 3) if duration > 0 else 0.0,
            "latency": self.latency.summary(),
            "service_latency": self.service.summary(),
            "status": dict(self.status),
            "errors": {
                k: {"count": n, "sample": self.error_samples.get(k)} for k, n in self.errors.items()
            },
            "bytes_in": self.bytes_in,
        }


def _totals_from_tick(tick: dict[str, Any]) -> tuple[_Totals, dict[str, _Totals]]:
    steps: dict[str, _Totals] = {}
    overall = _Totals()
    for name, d in tick["steps"].items():
        t = steps[name] = _Totals()
        t.add_step(d)
        overall.merge(t)
    return overall, steps


class RunAggregator:
    """Turns engine ticks into a chartable per-second series and a run summary."""

    def __init__(self, warmup: float = 0.0) -> None:
        self.warmup = warmup
        self.series: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._overall = _Totals()
        self._steps: dict[str, _Totals] = {}
        self._duration = 0.0
        self._dropped = 0
        self._max_lag_ms = 0.0

    def add_tick(self, tick: dict[str, Any]) -> dict[str, Any] | None:
        """Add a tick; returns the chart point, or None for a too-short final tick."""
        overall, steps = _totals_from_tick(tick)
        window = tick["window"]
        self.events.extend(tick.get("events", []))
        self._max_lag_ms = max(self._max_lag_ms, tick.get("loop_lag_ms", 0.0))

        if tick["start"] >= self.warmup:
            self._overall.merge(overall)
            for name, t in steps.items():
                self._steps.setdefault(name, _Totals()).merge(t)
            self._duration += window
            self._dropped += tick["dropped"]

        if tick.get("final") and window < _MIN_CHART_WINDOW:
            return None
        point = {
            "t": tick["t"],
            "time": round(tick["start"] + window, 3),
            "target": round(tick["target"], 3),
            "active_vus": tick["active_vus"],
            "in_flight": tick["in_flight"],
            "dropped": tick["dropped"],
            "loop_lag_ms": round(tick.get("loop_lag_ms", 0.0), 3),
            "state": tick.get("state"),
            "events": tick.get("events", []),
            "overall": overall.point(window),
            "steps": {name: t.point(window) for name, t in steps.items()},
        }
        self.series.append(point)
        return point

    def summary(self) -> dict[str, Any]:
        return {
            "duration": round(self._duration, 3),
            "dropped": self._dropped,
            "max_loop_lag_ms": round(self._max_lag_ms, 3),
            **self._overall.summary(self._duration),
            "steps": {name: t.summary(self._duration) for name, t in self._steps.items()},
        }
