from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import uvicorn

from loadpilot.config import RequestSpec, TestPlan
from loadpilot.demo_server import create_app
from loadpilot.engine import Engine, Response
from loadpilot.metrics import RunAggregator


class FakeTransport:
    """Responds after a fixed delay. ``responder`` can customise each response."""

    def __init__(
        self,
        latency: float = 0.01,
        responder: Callable[[RequestSpec], Response] | None = None,
    ) -> None:
        self.latency = latency
        self.responder = responder
        self.calls = 0

    async def send(self, request: RequestSpec) -> Response:
        self.calls += 1
        await asyncio.sleep(self.latency)
        if self.responder is not None:
            return self.responder(request)
        return Response(status=200, bytes_in=10)

    async def aclose(self) -> None:
        pass


def make_plan(load: dict[str, Any], url: str = "http://test.local/", **extra: Any) -> TestPlan:
    return TestPlan.model_validate({"request": {"url": url}, "load": load, **extra})


async def run_engine(
    engine: Engine, aggregator: RunAggregator | None = None
) -> tuple[RunAggregator, list[dict[str, Any]]]:
    aggregator = aggregator or RunAggregator(engine.plan.warmup)
    ticks: list[dict[str, Any]] = []

    def on_tick(tick: dict[str, Any]) -> None:
        ticks.append(tick)
        aggregator.add_tick(tick)

    engine._on_tick = on_tick
    await engine.run()
    return aggregator, ticks


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def demo_url() -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(
        create_app(rate_limit_capacity=5, rate_limit_per_second=5.0),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("demo server did not start")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
