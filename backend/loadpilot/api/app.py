from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import __version__
from ..config import Limits, TestPlan
from ..controller import (
    LimitError,
    RunActiveError,
    RunConflictError,
    RunManager,
    RunNotActiveError,
)
from ..storage import Store

DEFAULT_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

_UI_MISSING = """<!doctype html><title>LoadPilot</title>
<p>The LoadPilot API is running, but the web UI hasn't been built.</p>
<p>Build it with <code>cd frontend &amp;&amp; pnpm install &amp;&amp; pnpm build</code>,
or use the Vite dev server (<code>pnpm dev</code>).</p>"""


class ControlRequest(BaseModel):
    action: Literal["pause", "resume", "stop", "abort", "set_load"]
    value: float | None = Field(default=None, ge=0, le=10_000_000)


class RunUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)


class BaselineRequest(BaseModel):
    on: bool


class SettingsBody(BaseModel):
    limits: Limits


def create_app(
    *,
    static_dir: Path | None = DEFAULT_STATIC_DIR,
    demo: bool = True,
    allowed_hosts: list[str] | None = None,
    db_path: str | Path | None = None,
) -> FastAPI:
    """``db_path=None`` keeps history in memory (used by tests)."""
    store = Store(db_path or ":memory:")
    manager = RunManager(store)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await manager.shutdown()
        store.close()

    app = FastAPI(
        title="LoadPilot",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.manager = manager
    # Rejects requests whose Host header isn't ours (blocks DNS-rebinding attacks
    # from web pages trying to drive a LoadPilot running on localhost).
    hosts = allowed_hosts or list(LOOPBACK_HOSTS)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    def limit_error(e: LimitError) -> HTTPException:
        return HTTPException(
            400, {"message": "This test is over the safety limits.", "errors": e.errors}
        )

    def finished_only(action: Callable[[], bool]) -> None:
        try:
            found = action()
        except RunActiveError:
            raise HTTPException(409, "stop the run first") from None
        if not found:
            raise HTTPException(404, "run not found")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "demo": demo}

    @app.get("/api/settings")
    async def get_settings() -> dict[str, Any]:
        return {"limits": manager.limits.model_dump(mode="json")}

    @app.put("/api/settings")
    async def put_settings(body: SettingsBody) -> dict[str, Any]:
        manager.set_limits(body.limits)
        return {"limits": manager.limits.model_dump(mode="json")}

    @app.get("/api/runs")
    async def list_runs(
        q: str = Query("", max_length=200),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        items, total = manager.list_info(q=q, limit=limit, offset=offset)
        return {"items": items, "total": total}

    @app.post("/api/runs", status_code=201)
    async def start_run(plan: TestPlan) -> dict[str, Any]:
        try:
            run = manager.start(plan)
        except RunConflictError as e:
            raise HTTPException(
                409, {"message": "another test is already running", "run_id": str(e)}
            ) from None
        except LimitError as e:
            raise limit_error(e) from None
        return run.info(full=True)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        info = manager.info(run_id)
        if info is None:
            raise HTTPException(404, "run not found")
        return info

    @app.patch("/api/runs/{run_id}")
    async def update_run(run_id: str, body: RunUpdate) -> dict[str, Any]:
        finished_only(lambda: manager.update(run_id, name=body.name, notes=body.notes))
        return manager.info(run_id, full=False) or {}

    @app.put("/api/runs/{run_id}/baseline")
    async def set_baseline(run_id: str, body: BaselineRequest) -> dict[str, Any]:
        finished_only(lambda: manager.set_baseline(run_id, body.on))
        return manager.info(run_id, full=False) or {}

    @app.delete("/api/runs/{run_id}", status_code=204)
    async def delete_run(run_id: str) -> None:
        finished_only(lambda: manager.delete(run_id))

    @app.post("/api/runs/{run_id}/control")
    async def control_run(run_id: str, body: ControlRequest) -> dict[str, Any]:
        run = manager.live(run_id)
        if run is None:
            if manager.info(run_id, full=False) is None:
                raise HTTPException(404, "run not found")
            raise HTTPException(409, "this run has already ended")
        try:
            manager.control(run, body.action, body.value)
        except RunNotActiveError:
            raise HTTPException(409, "this run has already ended") from None
        except LimitError as e:
            raise limit_error(e) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return run.info()

    @app.websocket("/ws/runs/{run_id}")
    async def run_stream(websocket: WebSocket, run_id: str) -> None:
        # Browsers don't apply CORS to WebSockets, so check the Origin ourselves.
        if not _origin_allowed(websocket.headers.get("origin"), websocket.headers.get("host")):
            await websocket.send_denial_response(PlainTextResponse("origin not allowed", 403))
            return
        run = manager.live(run_id)
        if run is None:
            # Finished runs come from the store: send them once and close.
            info = manager.info(run_id)
            if info is None:
                await websocket.send_denial_response(PlainTextResponse("run not found", 404))
                return
            await websocket.accept()
            await websocket.send_json({"type": "snapshot", "run": info})
            await websocket.close()
            return
        await websocket.accept()
        queue = run.subscribe()
        try:
            await websocket.send_json({"type": "snapshot", "run": run.info(full=True)})
            while not run.done or not queue.empty():
                message = await queue.get()
                await websocket.send_json(message)
                if message["type"] == "finished":
                    break
            await websocket.close()
        except WebSocketDisconnect:
            pass
        finally:
            run.unsubscribe(queue)

    if demo:
        from ..demo_server import create_app as create_demo_app

        app.mount("/demo", create_demo_app())

    _mount_ui(app, static_dir)
    return app


def _origin_allowed(origin: str | None, host: str | None) -> bool:
    if origin is None:  # non-browser clients
        return True
    parsed = urlsplit(origin)
    if parsed.hostname in LOOPBACK_HOSTS:
        return True
    return parsed.netloc == host


def _mount_ui(app: FastAPI, static_dir: Path | None) -> None:
    index = static_dir / "index.html" if static_dir else None
    if static_dir is None or index is None or not index.is_file():

        @app.get("/", include_in_schema=False)
        async def ui_missing() -> HTMLResponse:
            return HTMLResponse(_UI_MISSING)

        return

    root = static_dir.resolve()
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str, request: Request) -> FileResponse:
        if path.startswith(("api/", "ws/")):
            raise HTTPException(404, "not found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")
