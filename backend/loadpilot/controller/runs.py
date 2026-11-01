from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from ..config import Limits, TestPlan
from ..engine import Engine
from ..metrics import RunAggregator
from ..storage import Store

log = logging.getLogger(__name__)

_SUBSCRIBER_QUEUE_SIZE = 256
_SENSITIVE_HEADER_PARTS = ("authorization", "cookie", "token", "secret", "api-key", "apikey")
_ACTIVE_STATUSES = {"pending", "running", "paused", "stopping"}
REDACTED = "••••••"


class RunConflictError(Exception):
    pass


class RunNotActiveError(Exception):
    """The action needs a running test, but this one has ended."""


class RunActiveError(Exception):
    """The action needs a finished test, but this one is still running."""


class LimitError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


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


def _list_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {k: summary[k] for k in ("requests", "rps", "error_rate", "duration")} | {
        "p95": summary["latency"]["p95"]
    }


def _stored_info(row: dict[str, Any], *, full: bool) -> dict[str, Any]:
    summary = row["summary"] or RunAggregator().summary()
    series = row.get("series") or []
    data: dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "mode": row["mode"],
        "target": series[-1]["target"] if series else 0.0,
        "elapsed": row["elapsed"],
        "total_duration": row["total_duration"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "error": row["error"],
        "notes": row["notes"],
        "is_baseline": row["is_baseline"],
    }
    if not full:
        data["summary"] = _list_summary(summary)
        return data
    data.update(plan=row["plan"], summary=summary, series=series, events=row["events"])
    return data


class Run:
    def __init__(self, plan: TestPlan, store: Store) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.plan = plan
        self.store = store
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
        summary = self.aggregator.summary()
        try:
            if point is not None:
                self.store.add_point(self.id, point)
            # Saved every second, so a crash mid-run still leaves usable results.
            self.store.update_run(
                self.id,
                status=self.status,
                elapsed=round(self.engine.elapsed(), 3),
                summary=summary,
                events=self.aggregator.events,
            )
        except Exception:
            log.exception("saving run %s failed", self.id)
        if point is not None:
            self.broadcast(
                {
                    "type": "point",
                    "point": point,
                    "status": self.status,
                    "elapsed": self.engine.elapsed(),
                    "summary": summary,
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
            "notes": "",
            "is_baseline": False,
        }
        if not full:
            data["summary"] = _list_summary(summary)
            return data
        data.update(
            plan=redact_plan(self.plan.model_dump(mode="json", by_alias=True)),
            summary=summary,
            series=self.aggregator.series,
            events=self.aggregator.events,
        )
        return data


class RunManager:
    """Owns runs for this server process.

    One run at a time keeps the load generator's CPU for that run, so its numbers stay
    trustworthy. The active run lives in memory; finished runs are read from the store.
    """

    def __init__(self, store: Store) -> None:
        self.store = store
        interrupted = store.mark_interrupted(time.time())
        if interrupted:
            log.warning("marked %d run(s) from a previous server as interrupted", interrupted)
        self._limits = Limits.model_validate(store.get_setting("limits") or {})
        self._runs: dict[str, Run] = {}

    # ---- settings -------------------------------------------------------

    @property
    def limits(self) -> Limits:
        return self._limits

    def set_limits(self, limits: Limits) -> None:
        self.store.put_setting("limits", limits.model_dump(mode="json"))
        self._limits = limits

    # ---- queries --------------------------------------------------------

    def active(self) -> Run | None:
        return next((r for r in self._runs.values() if not r.done), None)

    def live(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def info(self, run_id: str, *, full: bool = True) -> dict[str, Any] | None:
        run = self._runs.get(run_id)
        if run is not None:
            return run.info(full=full)
        row = self.store.get_run(run_id)
        return None if row is None else _stored_info(row, full=full)

    def list_info(
        self, *, q: str = "", limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        rows, total = self.store.list_runs(q=q, limit=limit, offset=offset)
        items = []
        for row in rows:
            run = self._runs.get(row["id"])
            items.append(run.info() if run is not None else _stored_info(row, full=False))
        return items, total

    # ---- commands -------------------------------------------------------

    def start(self, plan: TestPlan) -> Run:
        current = self.active()
        if current is not None:
            raise RunConflictError(current.id)
        errors = self._limits.plan_errors(plan)
        if errors:
            raise LimitError(errors)
        run = Run(plan, self.store)
        self.store.insert_run(
            {
                "id": run.id,
                "name": plan.name,
                "status": "pending",
                "mode": plan.load.mode,
                "plan": redact_plan(plan.model_dump(mode="json", by_alias=True)),
                "total_duration": plan.load.total_duration,
                "created_at": run.created_at,
            }
        )
        self._runs[run.id] = run
        run.task = asyncio.create_task(self._execute(run))
        return run

    def control(self, run: Run, action: str, value: float | None = None) -> None:
        if run.done:
            raise RunNotActiveError(run.id)
        engine = run.engine
        if action == "set_load":
            if value is None:
                raise ValueError("set_load needs a value")
            if (error := self._limits.target_error(run.plan.load.mode, value)) is not None:
                raise LimitError([error])
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

    def _finished_row(self, run_id: str) -> dict[str, Any] | None:
        if run_id in self._runs:
            raise RunActiveError(run_id)
        row = self.store.get_run(run_id)
        if row is not None and row["status"] in _ACTIVE_STATUSES:
            raise RunActiveError(run_id)
        return row

    def update(self, run_id: str, *, name: str | None = None, notes: str | None = None) -> bool:
        if self._finished_row(run_id) is None:
            return False
        fields = {k: v for k, v in (("name", name), ("notes", notes)) if v is not None}
        self.store.update_run(run_id, **fields)
        return True

    def set_baseline(self, run_id: str, on: bool) -> bool:
        if self._finished_row(run_id) is None:
            return False
        self.store.set_baseline(run_id, on)
        return True

    def delete(self, run_id: str) -> bool:
        if self._finished_row(run_id) is None:
            return False
        return self.store.delete_run(run_id)

    async def shutdown(self) -> None:
        for run in self._runs.values():
            if not run.done:
                run.engine.abort()
        tasks = [r.task for r in self._runs.values() if r.task is not None]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, run: Run) -> None:
        run.started_at = time.time()
        try:
            self.store.update_run(run.id, started_at=run.started_at)
            await run.engine.run()
        except Exception as e:  # surfaced to the UI instead of killing the server
            log.exception("run %s failed", run.id)
            run.error = f"{type(e).__name__}: {e}"
        finally:
            run.ended_at = time.time()
            try:
                self.store.update_run(
                    run.id,
                    status=run.status,
                    elapsed=round(run.engine.elapsed(), 3),
                    ended_at=run.ended_at,
                    error=run.error,
                    summary=run.aggregator.summary(),
                    events=run.aggregator.events,
                )
            except Exception:
                log.exception("saving the end of run %s failed", run.id)
            run.broadcast({"type": "finished", "run": run.info(full=True)})
            # From here on the run is served from the store.
            self._runs.pop(run.id, None)
