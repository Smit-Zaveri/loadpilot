from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine
from enum import StrEnum
from typing import Any

from ..config import TestPlan
from ..metrics import MetricsCollector
from .transport import AiohttpTransport, Transport

log = logging.getLogger(__name__)

TickHandler = Callable[[dict[str, Any]], Awaitable[None] | None]

_CONTROL_INTERVAL = 0.05
_LAG_PROBE_INTERVAL = 0.05


class RunState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    FINISHED = "finished"
    ABORTED = "aborted"


class Engine:
    """Runs one test plan on the current asyncio event loop.

    Emits a *tick* (one-second metrics snapshot, see ``MetricsCollector.flush``)
    through ``on_tick``. Ticks are self-contained and mergeable, so the same
    format works for a local run and for distributed workers.

    Control methods (``set_load``, ``pause``, ``resume``, ``stop``, ``abort``)
    must be called from the same event loop.
    """

    def __init__(
        self,
        plan: TestPlan,
        *,
        transport: Transport | None = None,
        on_tick: TickHandler | None = None,
    ) -> None:
        self.plan = plan
        self.state = RunState.PENDING
        self._transport = transport
        self._owns_transport = transport is None
        self._on_tick = on_tick
        self._collector = MetricsCollector()

        self._manual_target: float | None = None
        self._resume = asyncio.Event()
        self._resume.set()
        self._stopping = False
        self._aborted = False

        self._tasks: set[asyncio.Task[None]] = set()
        self._in_flight = 0
        self._active_vus = 0

        self._t0 = 0.0
        self._paused_total = 0.0
        self._paused_at: float | None = None
        self._tick_index = 0
        self._last_tick_at = 0.0
        self._max_lag = 0.0
        self._pending_events: list[dict[str, Any]] = []

    # ---- public control -------------------------------------------------

    def elapsed(self) -> float:
        """Seconds of load profile completed (time spent paused is excluded)."""
        if self.state is RunState.PENDING:
            return 0.0
        now = time.perf_counter()
        paused = self._paused_total + (now - self._paused_at if self._paused_at else 0.0)
        return now - self._t0 - paused

    def current_target(self) -> float:
        if self._manual_target is not None:
            return self._manual_target
        return self.plan.load.target_at(self.elapsed())

    def set_load(self, target: float) -> None:
        if target < 0:
            raise ValueError("target must not be negative")
        self._manual_target = float(target)
        self._event("set_load", value=float(target))

    def pause(self) -> None:
        if self.state is RunState.RUNNING:
            self.state = RunState.PAUSED
            self._paused_at = time.perf_counter()
            self._resume.clear()
            self._event("pause")

    def resume(self) -> None:
        if self.state is RunState.PAUSED and self._paused_at is not None:
            self._paused_total += time.perf_counter() - self._paused_at
            self._paused_at = None
            self.state = RunState.RUNNING
            self._resume.set()
            self._event("resume")

    def stop(self) -> None:
        """Stop starting new iterations; in-flight ones get ``graceful_stop`` to finish."""
        if self.state in (RunState.RUNNING, RunState.PAUSED):
            self.resume()
            self._stopping = True
            self.state = RunState.STOPPING
            self._event("stop")

    def abort(self) -> None:
        """Cancel everything immediately."""
        if self.state in (RunState.FINISHED, RunState.ABORTED):
            return
        self._aborted = True
        self._stopping = True
        self._resume.set()
        self._event("abort")
        for task in list(self._tasks):
            task.cancel()

    # ---- run ------------------------------------------------------------

    async def run(self) -> None:
        if self.state is not RunState.PENDING:
            raise RuntimeError("an Engine can only be run once")
        if self._transport is None:
            self._transport = AiohttpTransport(
                verify=not self.plan.insecure,
                max_connections=max(self.plan.load.max_in_flight, 1),
            )
        self._t0 = self._last_tick_at = time.perf_counter()
        self.state = RunState.RUNNING
        tick_task = asyncio.create_task(self._tick_loop())
        lag_task = asyncio.create_task(self._lag_loop())
        try:
            if self.plan.load.mode == "vus":
                await self._closed_loop()
            else:
                await self._open_loop()
            await self._drain()
        finally:
            for t in (tick_task, lag_task):
                t.cancel()
            await asyncio.gather(tick_task, lag_task, return_exceptions=True)
            self.state = RunState.ABORTED if self._aborted else RunState.FINISHED
            await self._emit_tick(time.perf_counter(), final=True)
            if self._owns_transport:
                await self._transport.aclose()

    def _finished(self) -> bool:
        return self._stopping or self.elapsed() >= self.plan.load.total_duration

    async def _closed_loop(self) -> None:
        vus: list[asyncio.Event] = []
        while not self._finished():
            desired = max(0, int(self.current_target() + 0.5))
            while len(vus) < desired:
                stop = asyncio.Event()
                self._spawn(self._vu(stop))
                vus.append(stop)
            while len(vus) > desired:
                vus.pop().set()
            await asyncio.sleep(_CONTROL_INTERVAL)
        for stop in vus:
            stop.set()

    async def _vu(self, stop: asyncio.Event) -> None:
        self._active_vus += 1
        try:
            while not stop.is_set() and not self._stopping:
                if not self._resume.is_set():
                    await self._resume.wait()
                    continue
                self._in_flight += 1
                try:
                    await self._iteration(None)
                finally:
                    self._in_flight -= 1
                await asyncio.sleep(0)
        finally:
            self._active_vus -= 1

    async def _open_loop(self) -> None:
        max_in_flight = self.plan.load.max_in_flight
        last_at: float | None = None
        while not self._finished():
            if not self._resume.is_set():
                await self._resume.wait()
                last_at = None
                continue
            rate = self.current_target()
            if rate <= 0:
                await asyncio.sleep(_CONTROL_INTERVAL)
                last_at = None
                continue
            now = time.perf_counter()
            # The next start is computed from the *current* rate, so rate changes apply at once.
            planned = now if last_at is None else last_at + 1.0 / rate
            if planned > now:
                await asyncio.sleep(min(planned - now, _CONTROL_INTERVAL))
                continue
            last_at = planned
            if self._in_flight >= max_in_flight:
                self._collector.record_dropped()
                continue
            self._in_flight += 1
            self._spawn(self._open_iteration(planned))

    async def _open_iteration(self, planned: float) -> None:
        try:
            await self._iteration(planned)
        finally:
            self._in_flight -= 1

    async def _iteration(self, planned: float | None) -> None:
        assert self._transport is not None
        for i, step in enumerate(self.plan.steps):
            start = time.perf_counter()
            resp = await self._transport.send(step.request)
            end = time.perf_counter()
            # Open model: measure the first step from its *planned* start, so a
            # stalled target can't hide queueing delay (coordinated omission).
            origin = planned if i == 0 and planned is not None else start
            self._collector.record(
                step.name,
                latency_ms=(end - origin) * 1000.0,
                service_ms=(end - start) * 1000.0,
                status=resp.status,
                error=resp.error,
                error_detail=resp.error_detail,
                bytes_in=resp.bytes_in,
            )

    async def _drain(self) -> None:
        if self._tasks and not self._aborted:
            await asyncio.wait(set(self._tasks), timeout=self.plan.load.graceful_stop)
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("load task failed", exc_info=task.exception())

    # ---- ticks ----------------------------------------------------------

    async def _tick_loop(self) -> None:
        while True:
            boundary = self._t0 + self._tick_index + 1
            await asyncio.sleep(max(0.0, boundary - time.perf_counter()))
            await self._emit_tick(boundary)

    async def _lag_loop(self) -> None:
        while True:
            t = time.perf_counter()
            await asyncio.sleep(_LAG_PROBE_INTERVAL)
            lag = time.perf_counter() - t - _LAG_PROBE_INTERVAL
            self._max_lag = max(self._max_lag, lag)

    async def _emit_tick(self, end: float, *, final: bool = False) -> None:
        start, self._last_tick_at = self._last_tick_at, end
        tick: dict[str, Any] = {
            "t": self._tick_index,
            "start": round(start - self._t0, 6),
            "window": end - start,
            "final": final,
            "state": self.state.value,
            "elapsed": round(self.elapsed(), 3),
            "target": self.current_target(),
            "active_vus": self._active_vus,
            "in_flight": self._in_flight,
            "loop_lag_ms": self._max_lag * 1000.0,
            "events": self._pending_events,
            **self._collector.flush(),
        }
        self._tick_index += 1
        self._max_lag = 0.0
        self._pending_events = []
        if self._on_tick is None:
            return
        try:
            result = self._on_tick(tick)
            if inspect.isawaitable(result):
                await result
        except Exception:
            log.exception("tick handler failed")

    def _event(self, kind: str, **data: Any) -> None:
        elapsed = round(time.perf_counter() - self._t0, 3) if self._t0 else 0.0
        self._pending_events.append({"type": kind, "time": elapsed, **data})
