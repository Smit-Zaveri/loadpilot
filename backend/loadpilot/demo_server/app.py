"""Mock target so users can try LoadPilot without load-testing a real service."""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

_MAX_DELAY_MS = 60_000
_MAX_TOKENS = 4096
_WORDS = (
    "load testing helps you find the limits of a system before your users do . "
    "latency percentiles tell a more honest story than averages ."
).split()


class _TokenBucket:
    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity = capacity
        self.rate = refill_per_second
        self.tokens = float(capacity)
        self.updated = time.monotonic()

    def take(self) -> tuple[bool, int, float]:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True, int(self.tokens), 0.0
        return False, 0, (1 - self.tokens) / self.rate


def create_app(*, rate_limit_capacity: int = 20, rate_limit_per_second: float = 10.0) -> FastAPI:
    app = FastAPI(title="LoadPilot demo target", docs_url="/docs")
    bucket = _TokenBucket(rate_limit_capacity, rate_limit_per_second)

    @app.get("/")
    async def index() -> dict[str, Any]:
        return {
            "service": "loadpilot-demo",
            "endpoints": {
                "GET /fast": "responds immediately",
                "GET /slow?ms=200": "fixed delay",
                "GET /random-latency?min_ms=10&max_ms=500": "uniform random delay",
                "GET /flaky?error_rate=0.1&ms=0": "returns 500 with the given probability",
                "GET /status/{code}": "returns the given status code",
                "GET /rate-limited": (
                    f"token bucket: {rate_limit_capacity} burst, {rate_limit_per_second}/s, "
                    "429 + Retry-After when empty"
                ),
                "POST /echo": "returns the request body",
                "POST /v1/chat/completions": "OpenAI-style fake LLM, supports stream=true",
            },
        }

    @app.get("/fast")
    async def fast() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/slow")
    async def slow(ms: int = Query(200, ge=0, le=_MAX_DELAY_MS)) -> dict[str, int]:
        await asyncio.sleep(ms / 1000)
        return {"delay_ms": ms}

    @app.get("/random-latency")
    async def random_latency(
        min_ms: int = Query(10, ge=0, le=_MAX_DELAY_MS),
        max_ms: int = Query(500, ge=0, le=_MAX_DELAY_MS),
    ) -> dict[str, float]:
        delay = random.uniform(min(min_ms, max_ms), max(min_ms, max_ms))
        await asyncio.sleep(delay / 1000)
        return {"delay_ms": round(delay, 3)}

    @app.get("/flaky")
    async def flaky(
        error_rate: float = Query(0.1, ge=0, le=1),
        ms: int = Query(0, ge=0, le=_MAX_DELAY_MS),
    ) -> JSONResponse:
        if ms:
            await asyncio.sleep(ms / 1000)
        if random.random() < error_rate:
            return JSONResponse({"error": "simulated failure"}, status_code=500)
        return JSONResponse({"ok": True})

    @app.get("/status/{code}")
    async def status(code: int) -> Response:
        if not 100 <= code <= 599:
            return JSONResponse({"error": "code must be 100-599"}, status_code=400)
        return Response(status_code=code)

    @app.get("/rate-limited")
    async def rate_limited() -> JSONResponse:
        allowed, remaining, retry_after = bucket.take()
        headers = {
            "X-RateLimit-Limit": str(rate_limit_capacity),
            "X-RateLimit-Remaining": str(remaining),
        }
        if not allowed:
            headers["Retry-After"] = f"{retry_after:.3f}"
            return JSONResponse({"error": "rate limited"}, status_code=429, headers=headers)
        return JSONResponse({"ok": True}, headers=headers)

    @app.post("/echo")
    async def echo(request: Request) -> Response:
        body = await request.body()
        return Response(body, media_type=request.headers.get("content-type", "text/plain"))

    @app.post("/v1/chat/completions", response_model=None)
    async def chat(request: Request) -> JSONResponse | StreamingResponse:
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"error": "body must be JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
        demo = payload.get("demo") or {}
        max_tokens = _clamp_int(payload.get("max_tokens", 64), 1, _MAX_TOKENS)
        ttft = _clamp_int(demo.get("ttft_ms", 200), 0, _MAX_DELAY_MS) / 1000
        tps = max(1.0, min(float(demo.get("tokens_per_second", 50)), 10_000.0))
        model = str(payload.get("model", "demo-model"))
        prompt_tokens = sum(
            len(str(m.get("content", "")).split())
            for m in payload.get("messages", [])
            if isinstance(m, dict)
        )
        tokens = [_WORDS[i % len(_WORDS)] for i in range(max_tokens)]
        cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": max_tokens,
            "total_tokens": prompt_tokens + max_tokens,
        }

        if not payload.get("stream"):
            await asyncio.sleep(ttft + max_tokens / tps)
            return JSONResponse(
                {
                    "id": cid,
                    "object": "chat.completion",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": " ".join(tokens)},
                            "finish_reason": "length",
                        }
                    ],
                    "usage": usage,
                }
            )

        async def stream() -> AsyncIterator[str]:
            await asyncio.sleep(ttft)
            for i, tok in enumerate(tokens):
                if i:
                    await asyncio.sleep(1 / tps)
                chunk = {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": tok + " "}}],
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            final = {
                "id": cid,
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "length"}],
                "usage": usage,
            }
            yield f"data: {json.dumps(final)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def _clamp_int(value: object, lo: int, hi: int) -> int:
    try:
        n = int(float(str(value)))
    except ValueError:
        n = lo
    return max(lo, min(n, hi))
