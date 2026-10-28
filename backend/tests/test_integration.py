"""End-to-end: real HTTP against the built-in demo server."""

import json

import httpx
import pytest
from typer.testing import CliRunner

from loadpilot.cli import app
from loadpilot.engine import Engine

from .conftest import make_plan, run_engine


async def test_latency_accuracy_against_known_delay(demo_url):
    plan = make_plan({"rate": 30, "duration": 2}, url=f"{demo_url}/slow?ms=100")
    agg, _ = await run_engine(Engine(plan))
    s = agg.summary()
    assert s["failed"] == 0
    assert s["requests"] == pytest.approx(60, abs=4)
    assert 99 <= s["latency"]["p50"] <= 130
    assert s["status"] == {"200": s["requests"]}


async def test_url_query_string_is_kept_and_merged_with_params(demo_url):
    from loadpilot.config import RequestSpec
    from loadpilot.engine import AiohttpTransport

    transport = AiohttpTransport()
    try:
        only_url = await transport.send(RequestSpec(url=f"{demo_url}/status/204?x=1"))
        merged = await transport.send(
            RequestSpec(url=f"{demo_url}/random-latency?min_ms=0", params={"max_ms": 0})
        )
    finally:
        await transport.aclose()
    assert only_url.status == 204
    assert merged.status == 200
    assert merged.bytes_in == len(b'{"delay_ms":0.0}')


async def test_rate_limited_endpoint_returns_429s(demo_url):
    plan = make_plan({"rate": 40, "duration": 1}, url=f"{demo_url}/rate-limited")
    agg, _ = await run_engine(Engine(plan))
    status = agg.summary()["status"]
    assert status.get("429", 0) > 0
    assert status.get("200", 0) >= 5


async def test_connection_errors_are_reported():
    plan = make_plan({"vus": 1, "duration": 0.3}, url="http://127.0.0.1:1/")
    agg, _ = await run_engine(Engine(plan))
    s = agg.summary()
    assert s["error_rate"] == 1.0
    assert "connect_error" in s["errors"]


async def test_demo_chat_streams_openai_chunks(demo_url):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{demo_url}/v1/chat/completions",
            json={
                "stream": True,
                "max_tokens": 3,
                "demo": {"ttft_ms": 0, "tokens_per_second": 1000},
                "messages": [{"role": "user", "content": "hi there"}],
            },
        )
    lines = [ln for ln in resp.text.splitlines() if ln.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(ln[6:]) for ln in lines[:-1]]
    assert len(chunks) == 4
    assert chunks[-1]["usage"] == {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}


def test_cli_run_writes_json(demo_url, tmp_path):
    out = tmp_path / "result.json"
    result = CliRunner().invoke(
        app,
        [
            "run",
            "--url",
            f"{demo_url}/fast",
            "--rate",
            "20",
            "--duration",
            "1s",
            "--out",
            str(out),
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Summary" in result.output
    data = json.loads(out.read_text())
    assert data["state"] == "finished"
    assert data["summary"]["requests"] == pytest.approx(20, abs=3)
    assert data["plan"]["load"]["mode"] == "rate"


def test_cli_rejects_bad_input(tmp_path):
    runner = CliRunner()
    assert runner.invoke(app, ["run"]).exit_code == 2
    both = ["run", "--url", "http://x", "--vus", "1", "--rate", "1"]
    assert runner.invoke(app, both).exit_code == 2
    bad = tmp_path / "bad.yaml"
    bad.write_text("request: {url: 'ftp://x'}\nload: {vus: 1, duration: 1}\n")
    result = runner.invoke(app, ["run", str(bad)])
    assert result.exit_code == 2
