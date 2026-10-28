import asyncio
import time

import pytest

from loadpilot.config import TestPlan
from loadpilot.engine import Engine, Response, RunState

from .conftest import FakeTransport, make_plan, run_engine


async def test_closed_model_throughput_matches_vus_over_latency():
    transport = FakeTransport(latency=0.05)
    engine = Engine(make_plan({"vus": 10, "duration": 1}), transport=transport)
    agg, ticks = await run_engine(engine)
    # 10 VUs * (1s / 50ms) = 200 iterations
    assert 150 <= agg.summary()["requests"] <= 210
    assert ticks[0]["active_vus"] == 10
    assert engine.state is RunState.FINISHED


async def test_open_model_hits_target_rate():
    transport = FakeTransport(latency=0.02)
    engine = Engine(make_plan({"rate": 200, "duration": 1.5}), transport=transport)
    agg, _ = await run_engine(engine)
    assert agg.summary()["requests"] == pytest.approx(300, rel=0.07)
    assert agg.summary()["dropped"] == 0


async def test_open_model_drops_when_max_in_flight_reached():
    transport = FakeTransport(latency=2.0)
    plan = make_plan({"rate": 100, "duration": 1, "max_in_flight": 10, "graceful_stop": 3})
    agg, _ = await run_engine(Engine(plan, transport=transport))
    s = agg.summary()
    assert transport.calls == 10
    assert s["dropped"] == pytest.approx(90, abs=8)


async def test_open_model_latency_includes_queueing_delay():
    """When the event loop stalls, latency is measured from the planned start."""
    transport = FakeTransport(latency=0.001)
    engine = Engine(make_plan({"rate": 100, "duration": 1}), transport=transport)

    async def stall():
        await asyncio.sleep(0.3)
        time.sleep(0.2)  # block the loop: ~20 arrivals are now late

    stall_task = asyncio.create_task(stall())
    agg, _ = await run_engine(engine)
    await stall_task
    s = agg.summary()
    assert s["latency"]["max"] > 150
    assert s["service_latency"]["p50"] < 20


async def test_ramp_increases_vus():
    plan = make_plan({"stages": [{"duration": 2, "target": 10}]})
    _, ticks = await run_engine(Engine(plan, transport=FakeTransport()))
    assert ticks[0]["active_vus"] < ticks[1]["active_vus"]
    assert 7 <= ticks[1]["active_vus"] <= 10


async def test_set_load_changes_rate_mid_run():
    engine = Engine(make_plan({"rate": 20, "duration": 2}), transport=FakeTransport(0.005))

    async def bump():
        await asyncio.sleep(1.0)
        engine.set_load(200)

    task = asyncio.create_task(bump())
    agg, ticks = await run_engine(engine)
    await task
    first, second = ticks[0], ticks[1]
    assert first["steps"]["request"]["requests"] == pytest.approx(20, abs=3)
    assert second["steps"]["request"]["requests"] == pytest.approx(200, rel=0.1)
    assert any(e["type"] == "set_load" and e["value"] == 200 for e in agg.events)


async def test_pause_freezes_profile_and_sends_nothing():
    engine = Engine(make_plan({"vus": 2, "duration": 1}), transport=FakeTransport(0.01))

    async def pause_then_resume():
        await asyncio.sleep(0.3)
        engine.pause()
        await asyncio.sleep(0.05)  # let in-flight iterations finish
        calls = engine._transport.calls
        await asyncio.sleep(0.5)
        assert engine._transport.calls == calls
        engine.resume()

    task = asyncio.create_task(pause_then_resume())
    started = time.perf_counter()
    await run_engine(engine)
    await task
    assert time.perf_counter() - started >= 1.5


async def test_stop_ends_run_early():
    engine = Engine(make_plan({"vus": 5, "duration": 30}), transport=FakeTransport(0.01))
    asyncio.get_running_loop().call_later(0.3, engine.stop)
    started = time.perf_counter()
    agg, _ = await run_engine(engine)
    assert time.perf_counter() - started < 1.5
    assert engine.state is RunState.FINISHED
    assert agg.summary()["requests"] > 0


async def test_abort_cancels_in_flight_requests():
    engine = Engine(make_plan({"vus": 5, "duration": 30}), transport=FakeTransport(10))
    asyncio.get_running_loop().call_later(0.2, engine.abort)
    started = time.perf_counter()
    agg, _ = await run_engine(engine)
    assert time.perf_counter() - started < 1.0
    assert engine.state is RunState.ABORTED
    assert agg.summary()["requests"] == 0


async def test_errors_and_http_failures_are_counted():
    responses = iter(
        [Response(200), Response(500), Response(None, error="timeout", error_detail="t/o")] * 1000
    )
    transport = FakeTransport(0.001, responder=lambda _: next(responses))
    agg, _ = await run_engine(Engine(make_plan({"vus": 1, "duration": 0.5}), transport=transport))
    s = agg.summary()
    assert s["failed"] > 0
    assert s["error_rate"] == pytest.approx(2 / 3, abs=0.05)
    assert s["errors"]["timeout"]["sample"] == "t/o"
    assert set(s["status"]) == {"200", "500"}


async def test_multi_step_iteration_records_each_step():
    plan = TestPlan.model_validate(
        {
            "steps": [
                {"name": "a", "request": {"url": "http://x/a"}},
                {"name": "b", "request": {"url": "http://x/b"}},
            ],
            "load": {"vus": 1, "duration": 0.3},
        }
    )
    agg, _ = await run_engine(Engine(plan, transport=FakeTransport(0.01)))
    steps = agg.summary()["steps"]
    assert set(steps) == {"a", "b"}
    assert abs(steps["a"]["requests"] - steps["b"]["requests"]) <= 1


async def test_engine_runs_only_once():
    engine = Engine(make_plan({"vus": 1, "duration": 0.1}), transport=FakeTransport())
    await engine.run()
    with pytest.raises(RuntimeError):
        await engine.run()
