from __future__ import annotations

from typing import Any

from .histogram import Histogram


class _StepWindow:
    __slots__ = (
        "requests",
        "failed",
        "status",
        "errors",
        "error_samples",
        "bytes_in",
        "latency",
        "service",
    )

    def __init__(self) -> None:
        self.requests = 0
        self.failed = 0
        self.status: dict[str, int] = {}
        self.errors: dict[str, int] = {}
        self.error_samples: dict[str, str] = {}
        self.bytes_in = 0
        self.latency = Histogram()
        self.service = Histogram()

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "failed": self.failed,
            "status": self.status,
            "errors": self.errors,
            "error_samples": self.error_samples,
            "bytes_in": self.bytes_in,
            "latency": self.latency.to_dict(),
            "service": self.service.to_dict(),
        }


class MetricsCollector:
    """Accumulates raw results for the current one-second window.

    Not thread-safe: used from a single asyncio event loop.
    """

    def __init__(self) -> None:
        self._steps: dict[str, _StepWindow] = {}
        self._dropped = 0

    def record(
        self,
        step: str,
        *,
        latency_ms: float,
        service_ms: float,
        status: int | None,
        error: str | None = None,
        error_detail: str | None = None,
        bytes_in: int = 0,
    ) -> None:
        w = self._steps.get(step)
        if w is None:
            w = self._steps[step] = _StepWindow()
        w.requests += 1
        w.bytes_in += bytes_in
        w.latency.record(latency_ms)
        w.service.record(service_ms)
        if status is not None:
            key = str(status)
            w.status[key] = w.status.get(key, 0) + 1
        if error is not None:
            w.errors[error] = w.errors.get(error, 0) + 1
            if error not in w.error_samples and error_detail:
                w.error_samples[error] = error_detail[:500]
        if error is not None or (status is not None and status >= 400):
            w.failed += 1

    def record_dropped(self) -> None:
        self._dropped += 1

    def flush(self) -> dict[str, Any]:
        data = {
            "steps": {name: w.to_dict() for name, w in self._steps.items()},
            "dropped": self._dropped,
        }
        self._steps = {}
        self._dropped = 0
        return data
