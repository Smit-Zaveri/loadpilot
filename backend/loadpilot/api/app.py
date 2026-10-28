from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import __version__
from ..config import TestPlan
from ..controller import RunConflictError, RunManager, RunNotActiveError

DEFAULT_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

_UI_MISSING = """<!doctype html><title>LoadPilot</title>
<p>The LoadPilot API is running, but the web UI hasn't been built.</p>
<p>Build it with <code>cd frontend &amp;&amp; pnpm install &amp;&amp; pnpm build</code>,
or use the Vite dev server (<code>pnpm dev</code>).</p>"""


class ControlRequest(BaseModel):
    action: Literal["pause", "resume", "stop", "abort", "set_load"]
    value: float | None = Field(default=None, ge=0, le=1_000_000)


def create_app(
    *,
    static_dir: Path | None = DEFAULT_STATIC_DIR,
    demo: bool = True,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    manager = RunManager()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await manager.shutdown()

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

    def get_run_or_404(run_id: str) -> Any:
        run = manager.get(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return run

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "demo": demo}

    @app.get("/api/runs")
    async def list_runs() -> list[dict[str, Any]]:
        return [r.info() for r in manager.list()]

    @app.post("/api/runs", status_code=201)
    async def start_run(plan: TestPlan) -> dict[str, Any]:
        try:
            run = manager.start(plan)
        except RunConflictError as e:
            raise HTTPException(
                409, {"message": "another test is already running", "run_id": str(e)}
            ) from None
        return run.info(full=True)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        info: dict[str, Any] = get_run_or_404(run_id).info(full=True)
        return info

    @app.post("/api/runs/{run_id}/control")
    async def control_run(run_id: str, body: ControlRequest) -> dict[str, Any]:
        run = get_run_or_404(run_id)
        try:
            manager.control(run, body.action, body.value)
        except RunNotActiveError:
            raise HTTPException(409, "this run has already ended") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        info: dict[str, Any] = run.info()
        return info

    @app.websocket("/ws/runs/{run_id}")
    async def run_stream(websocket: WebSocket, run_id: str) -> None:
        # Browsers don't apply CORS to WebSockets, so check the Origin ourselves.
        if not _origin_allowed(websocket.headers.get("origin"), websocket.headers.get("host")):
            await websocket.send_denial_response(PlainTextResponse("origin not allowed", 403))
            return
        run = manager.get(run_id)
        if run is None:
            await websocket.send_denial_response(PlainTextResponse("run not found", 404))
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
