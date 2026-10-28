from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from ..config import TestPlan
from ..engine import Engine
from ..metrics import RunAggregator

log = logging.getLogger(__name__)

_SUBSCRIBER_QUEUE_SIZE = 256
_SENSITIVE_HEADER_PARTS = ("authorization", "cookie", "token", "secret", "api-key", "apikey")
REDACTED = "••••••"


class RunConflictError(Exception):
    pass


class RunNotActiveError(Exception):
    pass


def redact_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Copy of a dumped plan with secret-looking header values masked."""
    steps = []
    for step in plan.get("steps", []):
        request = dict(step["request"])
        request["headers"] = {
            k: REDACTED if any(p in k.lower() for p in _SENSITIVE_HEADER_PARTS) else v
            for k, v in request.get("headers", {}).items()
        }
        steps.append({**step, "request": request})
    return {**plan, "steps": steps}


class Run:
    def __init__(self, plan: TestPlan) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.plan = plan
        self.created_at = time.time()
        self.started_at: float | None = None
        self.ended_at: float | None = None
        self.error: str | None = None
        self.aggregator = RunAggregator(plan.warmup)
        self.engine = Engine(plan, on_tick=self._on_tick)
        self.task: asyncio.Task[None] | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def status(self) -> str:
        return "failed" if self.error else self.engine.state.value

    @property
    def done(self) -> bool:
        return self.ended_at is not None

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(_SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def broadcast(self, message: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A client that can't keep up is dropped rather than slowing the run.
                self._subscribers.discard(queue)

    def _on_tick(self, tick: dict[str, Any]) -> None:
        point = self.aggregator.add_tick(tick)
        if point is not None:
            self.broadcast(
                {
                    "type": "point",
                    "point": point,
                    "status": self.status,
                    "elapsed": self.engine.elapsed(),
                    "summary": self.aggregator.summary(),
                }
            )

    def info(self, *, full: bool = False) -> dict[str, Any]:
        summary = self.aggregator.summary()
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.plan.name,
            "status": self.status,
            "mode": self.plan.load.mode,
            "target": self.engine.current_target(),
            "elapsed": round(self.engine.elapsed(), 3),
            "total_duration": self.plan.load.total_duration,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "error": self.error,
        }
        if not full:
            data["summary"] = {
                k: summary[k] for k in ("requests", "rps", "error_rate", "duration")
            } | {"p95": summary["latency"]["p95"]}
            return data
        data.update(
            plan=redact_plan(self.plan.model_dump(mode="json", by_alias=True)),
            summary=summary,
            series=self.aggregator.series,
            events=self.aggregator.events,
        )
        return data


class RunManager:
    """Owns runs for this server process. One run at a time keeps the load
    generator's CPU for that run, so its numbers stay trustworthy."""

    def __init__(self, max_history: int = 50) -> None:
        self._runs: dict[str, Run] = {}
        self._max_history = max_history

    def active(self) -> Run | None:
        return next((r for r in self._runs.values() if not r.done), None)

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list(self) -> list[Run]:
        return sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)

    def start(self, plan: TestPlan) -> Run:
        current = self.active()
        if current is not None:
            raise RunConflictError(current.id)
        run = Run(plan)
        self._runs[run.id] = run
        run.task = asyncio.create_task(self._execute(run))
        self._trim()
        return run

    def control(self, run: Run, action: str, value: float | None = None) -> None:
        if run.done:
            raise RunNotActiveError(run.id)
        engine = run.engine
        if action == "set_load":
            if value is None:
                raise ValueError("set_load needs a value")
            engine.set_load(value)
        elif action == "pause":
            engine.pause()
        elif action == "resume":
            engine.resume()
        elif action == "stop":
            engine.stop()
        elif action == "abort":
            engine.abort()
        else:
            raise ValueError(f"unknown action {action!r}")
        run.broadcast({"type": "status", "status": run.status, "target": engine.current_target()})

    async def shutdown(self) -> None:
        for run in self._runs.values():
            if not run.done:
                run.engine.abort()
        tasks = [r.task for r in self._runs.values() if r.task is not None]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, run: Run) -> None:
        run.started_at = time.time()
        try:
            await run.engine.run()
        except Exception as e:  # surfaced to the UI instead of killing the server
            log.exception("run %s failed", run.id)
            run.error = f"{type(e).__name__}: {e}"
        finally:
            run.ended_at = time.time()
            run.broadcast({"type": "finished", "run": run.info(full=True)})

    def _trim(self) -> None:
        finished = [r for r in self.list() if r.done]
        for run in finished[self._max_history :]:
            del self._runs[run.id]
