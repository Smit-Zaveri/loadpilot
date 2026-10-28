import time

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from loadpilot.api import LOOPBACK_HOSTS, create_app
from loadpilot.controller import redact_plan

# Starlette's TestClient always sends WebSocket requests with Host "testserver".
TEST_HOSTS = [*LOOPBACK_HOSTS, "testserver"]


@pytest.fixture
def client(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>ui</html>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    with TestClient(
        create_app(static_dir=static, allowed_hosts=TEST_HOSTS), base_url="http://127.0.0.1"
    ) as c:
        yield c


def plan(url, load=None, **extra):
    return {
        "name": "api-test",
        "request": {"url": url},
        "load": load or {"rate": 20, "duration": 1},
        **extra,
    }


def wait_until_done(client, run_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["ended_at"] is not None:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["demo"] is True


def test_run_lifecycle_over_websocket(client, demo_url):
    resp = client.post("/api/runs", json=plan(f"{demo_url}/fast"))
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    messages = []
    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] == "finished":
                break
    assert messages[0]["type"] == "snapshot"
    points = [m for m in messages if m["type"] == "point"]
    assert points
    assert points[-1]["summary"]["requests"] > 0
    final = messages[-1]["run"]
    assert final["status"] == "finished"
    assert final["summary"]["requests"] == pytest.approx(20, abs=3)
    assert final["series"]

    runs = client.get("/api/runs").json()
    assert runs[0]["id"] == run_id
    assert runs[0]["summary"]["requests"] == final["summary"]["requests"]


def test_websocket_for_finished_run_sends_snapshot_then_closes(client, demo_url):
    run_id = client.post(
        "/api/runs", json=plan(f"{demo_url}/fast", {"vus": 1, "duration": 0.3})
    ).json()["id"]
    wait_until_done(client, run_id)
    with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert msg["run"]["status"] == "finished"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_only_one_active_run(client, demo_url):
    first = client.post("/api/runs", json=plan(f"{demo_url}/fast", {"vus": 1, "duration": 30}))
    second = client.post("/api/runs", json=plan(f"{demo_url}/fast"))
    assert second.status_code == 409
    assert second.json()["detail"]["run_id"] == first.json()["id"]
    client.post(f"/api/runs/{first.json()['id']}/control", json={"action": "abort"})
    wait_until_done(client, first.json()["id"])


def test_controls(client, demo_url):
    run_id = client.post(
        "/api/runs", json=plan(f"{demo_url}/fast", {"rate": 10, "duration": 30})
    ).json()["id"]

    def control(**body):
        return client.post(f"/api/runs/{run_id}/control", json=body)

    assert control(action="set_load", value=25).json()["target"] == 25
    assert control(action="set_load").status_code == 400
    assert control(action="set_load", value=-1).status_code == 422
    assert control(action="explode").status_code == 422
    assert control(action="pause").json()["status"] == "paused"
    assert control(action="resume").json()["status"] == "running"
    assert control(action="stop").json()["status"] == "stopping"
    run = wait_until_done(client, run_id)
    assert run["status"] == "finished"
    assert [e["type"] for e in run["events"]] == ["set_load", "pause", "resume", "stop"]
    assert control(action="pause").status_code == 409


def test_invalid_plan_is_rejected(client):
    resp = client.post(
        "/api/runs", json={"request": {"url": "ftp://x"}, "load": {"vus": 1, "duration": 1}}
    )
    assert resp.status_code == 422
    assert client.get("/api/runs").json() == []


def test_non_json_body_is_rejected(client, demo_url):
    """A cross-site form or text/plain POST must not start a run (CSRF)."""
    import json

    resp = client.post(
        "/api/runs",
        content=json.dumps(plan(f"{demo_url}/fast")),
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == 422
    assert client.get("/api/runs").json() == []


def test_unknown_run(client):
    assert client.get("/api/runs/nope").status_code == 404
    assert client.post("/api/runs/nope/control", json={"action": "stop"}).status_code == 404
    with pytest.raises(WebSocketDenialResponse) as exc, client.websocket_connect("/ws/runs/nope"):
        pass
    assert exc.value.status_code == 404


def test_websocket_rejects_foreign_origin(client, demo_url):
    run_id = client.post(
        "/api/runs", json=plan(f"{demo_url}/fast", {"vus": 1, "duration": 0.2})
    ).json()["id"]
    with (
        pytest.raises(WebSocketDenialResponse) as exc,
        client.websocket_connect(f"/ws/runs/{run_id}", headers={"origin": "https://evil.example"}),
    ):
        pass
    assert exc.value.status_code == 403
    with client.websocket_connect(
        f"/ws/runs/{run_id}", headers={"origin": "http://localhost:5173"}
    ) as ws:
        assert ws.receive_json()["type"] == "snapshot"
    wait_until_done(client, run_id)


def test_foreign_host_header_is_rejected(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400


def test_secret_headers_are_redacted(client, demo_url):
    body = plan(f"{demo_url}/fast", {"vus": 1, "duration": 0.2})
    body["request"]["headers"] = {"Authorization": "Bearer abc", "X-Api-Key": "k", "Accept": "a"}
    run_id = client.post("/api/runs", json=body).json()["id"]
    headers = client.get(f"/api/runs/{run_id}").json()["plan"]["steps"][0]["request"]["headers"]
    assert headers == {"Authorization": "••••••", "X-Api-Key": "••••••", "Accept": "a"}
    wait_until_done(client, run_id)


def test_redact_plan_does_not_mutate_input():
    original = {"steps": [{"request": {"headers": {"Cookie": "c"}}}]}
    redact_plan(original)
    assert original["steps"][0]["request"]["headers"]["Cookie"] == "c"


def test_spa_and_static_files(client):
    assert client.get("/").text == "<html>ui</html>"
    assert client.get("/runs/abc123").text == "<html>ui</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/unknown").status_code == 404
    assert "nope" not in client.get("/../secret.txt").text
    assert "nope" not in client.get("/%2e%2e/secret.txt").text


def test_demo_target_is_mounted(client):
    assert client.get("/demo/fast").json() == {"ok": True}


def test_websocket_works_on_real_server(demo_url):
    """TestClient bypasses uvicorn, so check the real server can upgrade WebSockets."""
    import json

    import httpx
    from websockets.sync.client import connect

    from .conftest import serve

    for base in serve(create_app(static_dir=None)):
        run = httpx.post(
            f"{base}/api/runs", json=plan(f"{demo_url}/fast", {"vus": 1, "duration": 1.2})
        ).json()
        ws_url = base.replace("http://", "ws://") + f"/ws/runs/{run['id']}"
        types = []
        with connect(ws_url, origin=base, open_timeout=5) as ws:
            for raw in ws:
                types.append(json.loads(raw)["type"])
        assert types[0] == "snapshot"
        assert "point" in types
        assert types[-1] == "finished"


def test_ui_missing_page():
    with TestClient(
        create_app(static_dir=None, allowed_hosts=TEST_HOSTS), base_url="http://127.0.0.1"
    ) as c:
        assert "hasn't been built" in c.get("/").text
