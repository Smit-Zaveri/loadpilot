"""Phase 3-4: safety limits, saved history, baselines, settings."""

import time

import pytest
from fastapi.testclient import TestClient

from loadpilot.api import LOOPBACK_HOSTS, create_app
from loadpilot.storage import Store

TEST_HOSTS = [*LOOPBACK_HOSTS, "testserver"]


def make_client(db_path=None):
    return TestClient(
        create_app(static_dir=None, allowed_hosts=TEST_HOSTS, db_path=db_path),
        base_url="http://127.0.0.1",
    )


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path / "lp.db") as c:
        yield c


def plan(url, load, name="history-test"):
    return {"name": name, "request": {"url": url}, "load": load}


def run_to_end(client, body):
    resp = client.post("/api/runs", json=body)
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["ended_at"] is not None:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


# ---- limits ---------------------------------------------------------------


def test_default_limits(client):
    assert client.get("/api/settings").json() == {
        "limits": {"max_vus": 1000, "max_rate": 5000.0, "max_duration": 7200.0}
    }


def test_plan_over_limits_is_rejected(client, demo_url):
    client.put("/api/settings", json={"limits": {"max_vus": 5, "max_rate": 50, "max_duration": 60}})
    resp = client.post(
        "/api/runs",
        json=plan(
            f"{demo_url}/fast",
            {"stages": [{"duration": 30, "target": 3}, {"duration": 40, "target": 8}]},
        ),
    )
    assert resp.status_code == 400
    errors = resp.json()["detail"]["errors"]
    assert any("8 virtual users" in e for e in errors)
    assert any("70s" in e for e in errors)
    assert client.get("/api/runs").json()["total"] == 0


def test_set_load_over_limit_is_rejected(client, demo_url):
    client.put(
        "/api/settings", json={"limits": {"max_vus": 1000, "max_rate": 50, "max_duration": 60}}
    )
    run_id = client.post(
        "/api/runs", json=plan(f"{demo_url}/fast", {"rate": 10, "duration": 20})
    ).json()["id"]
    resp = client.post(f"/api/runs/{run_id}/control", json={"action": "set_load", "value": 51})
    assert resp.status_code == 400
    assert "over the limit of 50" in resp.json()["detail"]["errors"][0]
    ok = client.post(f"/api/runs/{run_id}/control", json={"action": "set_load", "value": 50})
    assert ok.json()["target"] == 50
    client.post(f"/api/runs/{run_id}/control", json={"action": "abort"})


def test_invalid_settings_are_rejected(client):
    bad = client.put(
        "/api/settings", json={"limits": {"max_vus": 0, "max_rate": 1, "max_duration": 1}}
    )
    assert bad.status_code == 422
    assert client.get("/api/settings").json()["limits"]["max_vus"] == 1000


def test_settings_persist(tmp_path):
    db = tmp_path / "lp.db"
    with make_client(db) as c:
        c.put("/api/settings", json={"limits": {"max_vus": 7, "max_rate": 8, "max_duration": "1m"}})
    with make_client(db) as c:
        assert c.get("/api/settings").json()["limits"] == {
            "max_vus": 7,
            "max_rate": 8.0,
            "max_duration": 60.0,
        }


# ---- history --------------------------------------------------------------


def test_history_survives_restart(tmp_path, demo_url):
    db = tmp_path / "lp.db"
    with make_client(db) as c:
        run = run_to_end(c, plan(f"{demo_url}/fast", {"rate": 20, "duration": 1.2}))
    with make_client(db) as c:
        listed = c.get("/api/runs").json()
        assert listed["total"] == 1
        stored = c.get(f"/api/runs/{run['id']}").json()
        assert stored["status"] == "finished"
        assert stored["summary"]["requests"] == run["summary"]["requests"]
        assert stored["series"] and stored["plan"]["name"] == "history-test"
        with c.websocket_connect(f"/ws/runs/{run['id']}") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert msg["run"]["summary"]["requests"] == run["summary"]["requests"]


def test_run_left_active_by_a_crash_is_marked_interrupted(tmp_path):
    db = tmp_path / "lp.db"
    store = Store(db)
    store.insert_run(
        {
            "id": "crashed",
            "name": "x",
            "status": "running",
            "mode": "vus",
            "plan": {"name": "x", "steps": []},
            "total_duration": 10,
            "created_at": 1.0,
        }
    )
    store.update_run("crashed", summary=None)
    store.close()
    with make_client(db) as c:
        run = c.get("/api/runs/crashed").json()
        assert run["status"] == "interrupted"
        assert run["summary"]["requests"] == 0  # empty summary, not an error


def test_search_paging_rename_notes_baseline_delete(client, demo_url):
    ids = [
        run_to_end(client, plan(f"{demo_url}/fast", {"vus": 1, "duration": 0.3}, name=n))["id"]
        for n in ("checkout", "login", "checkout")
    ]
    found = client.get("/api/runs", params={"q": "check"}).json()
    assert found["total"] == 2
    page = client.get("/api/runs", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3 and page["items"][0]["id"] == ids[1]

    renamed = client.patch(f"/api/runs/{ids[1]}", json={"name": "sign-in", "notes": "after fix"})
    assert renamed.json()["name"] == "sign-in"
    assert client.get(f"/api/runs/{ids[1]}").json()["notes"] == "after fix"
    assert client.patch(f"/api/runs/{ids[1]}", json={"name": ""}).status_code == 422

    client.put(f"/api/runs/{ids[0]}/baseline", json={"on": True})
    client.put(f"/api/runs/{ids[2]}/baseline", json={"on": True})
    flags = {r["id"]: r["is_baseline"] for r in client.get("/api/runs").json()["items"]}
    assert flags == {ids[0]: False, ids[1]: False, ids[2]: True}

    assert client.delete(f"/api/runs/{ids[0]}").status_code == 204
    assert client.get(f"/api/runs/{ids[0]}").status_code == 404
    assert client.delete(f"/api/runs/{ids[0]}").status_code == 404
    assert client.patch("/api/runs/nope", json={"notes": "x"}).status_code == 404


def test_active_run_cannot_be_edited_or_deleted(client, demo_url):
    run_id = client.post(
        "/api/runs", json=plan(f"{demo_url}/fast", {"vus": 1, "duration": 20})
    ).json()["id"]
    assert client.delete(f"/api/runs/{run_id}").status_code == 409
    assert client.patch(f"/api/runs/{run_id}", json={"notes": "x"}).status_code == 409
    assert client.put(f"/api/runs/{run_id}/baseline", json={"on": True}).status_code == 409
    listed = client.get("/api/runs").json()["items"][0]
    assert listed["id"] == run_id and listed["status"] in ("pending", "running")
    client.post(f"/api/runs/{run_id}/control", json={"action": "abort"})


def test_control_on_stored_run_says_ended(client, demo_url):
    run = run_to_end(client, plan(f"{demo_url}/fast", {"vus": 1, "duration": 0.3}))
    resp = client.post(f"/api/runs/{run['id']}/control", json={"action": "pause"})
    assert resp.status_code == 409
