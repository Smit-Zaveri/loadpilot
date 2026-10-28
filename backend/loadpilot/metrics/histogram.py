from __future__ import annotations

import math
from typing import Any

_FLOOR_MS = 0.001  # 1 µs; smaller values are recorded as 1 µs
_GROWTH = 1.01  # bucket width: ~1% relative error
_LOG_GROWTH = math.log(_GROWTH)


class Histogram:
    """Log-bucketed latency histogram (milliseconds).

    Accurate to ~1% relative error, uses memory proportional to the spread of
    values (not their count), and merges exactly, so per-second snapshots from
    many workers can be combined into run-wide percentiles.
    """

    __slots__ = ("buckets", "count", "total", "min", "max")

    def __init__(self) -> None:
        self.buckets: dict[int, int] = {}
        self.count = 0
        self.total = 0.0
        self.min = math.inf
        self.max = 0.0

    def record(self, value_ms: float) -> None:
        v = max(value_ms, _FLOOR_MS)
        idx = math.ceil(math.log(v / _FLOOR_MS) / _LOG_GROWTH)
        self.buckets[idx] = self.buckets.get(idx, 0) + 1
        self.count += 1
        self.total += v
        if v < self.min:
            self.min = v
        if v > self.max:
            self.max = v

    def merge(self, other: Histogram) -> None:
        for idx, n in other.buckets.items():
            self.buckets[idx] = self.buckets.get(idx, 0) + n
        self.count += other.count
        self.total += other.total
        self.min = min(self.min, other.min)
        self.max = max(self.max, other.max)

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count else 0.0

    def percentile(self, p: float) -> float:
        if self.count == 0:
            return 0.0
        rank = max(1, math.ceil(p / 100.0 * self.count))
        seen = 0
        for idx in sorted(self.buckets):
            seen += self.buckets[idx]
            if seen >= rank:
                upper = _FLOOR_MS * _GROWTH**idx
                return min(max(upper, self.min), self.max)
        return self.max

    def summary(self) -> dict[str, float]:
        return {
            "min": _round(self.min if self.count else 0.0),
            "mean": _round(self.mean),
            "p50": _round(self.percentile(50)),
            "p90": _round(self.percentile(90)),
            "p95": _round(self.percentile(95)),
            "p99": _round(self.percentile(99)),
            "max": _round(self.max),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "b": {str(k): v for k, v in self.buckets.items()},
            "n": self.count,
            "sum": self.total,
            "min": self.min if self.count else None,
            "max": self.max,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Histogram:
        h = cls()
        h.buckets = {int(k): int(v) for k, v in data["b"].items()}
        h.count = int(data["n"])
        h.total = float(data["sum"])
        h.min = math.inf if data["min"] is None else float(data["min"])
        h.max = float(data["max"])
        return h


def _round(v: float) -> float:
    return round(v, 3)
