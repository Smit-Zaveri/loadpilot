import sqlite3

import pytest

from loadpilot.storage import Store
from loadpilot.storage.db import MIGRATIONS


def run_row(run_id, name="test", created_at=1.0, status="finished"):
    return {
        "id": run_id,
        "name": name,
        "status": status,
        "mode": "vus",
        "plan": {"name": name, "steps": []},
        "total_duration": 10.0,
        "created_at": created_at,
    }


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "lp.db")
    yield s
    s.close()


def test_run_roundtrip_with_points(store):
    store.insert_run(run_row("a"))
    store.add_point("a", {"t": 1, "x": 2})
    store.add_point("a", {"t": 0, "x": 1})
    store.add_point("a", {"t": 1, "x": 3})  # replaced, not duplicated
    store.update_run("a", summary={"requests": 5}, events=[{"type": "pause"}], elapsed=4.5)
    run = store.get_run("a")
    assert run["plan"] == {"name": "test", "steps": []}
    assert run["summary"] == {"requests": 5}
    assert run["events"] == [{"type": "pause"}]
    assert run["series"] == [{"t": 0, "x": 1}, {"t": 1, "x": 3}]
    assert run["is_baseline"] is False
    assert store.get_run("missing") is None


def test_update_rejects_unknown_columns(store):
    store.insert_run(run_row("a"))
    with pytest.raises(ValueError):
        store.update_run("a", id="b")


def test_list_search_and_paging(store):
    for i, name in enumerate(["checkout", "login", "checkout v2", "100%_off"]):
        store.insert_run(run_row(f"r{i}", name=name, created_at=float(i)))
    items, total = store.list_runs()
    assert total == 4
    assert [r["id"] for r in items] == ["r3", "r2", "r1", "r0"]  # newest first
    items, total = store.list_runs(q="checkout")
    assert total == 2 and {r["id"] for r in items} == {"r0", "r2"}
    # LIKE wildcards in the query are matched literally.
    assert store.list_runs(q="%_")[1] == 1
    items, total = store.list_runs(limit=2, offset=1)
    assert total == 4 and [r["id"] for r in items] == ["r2", "r1"]


def test_baseline_is_unique_per_name(store):
    store.insert_run(run_row("a", name="checkout"))
    store.insert_run(run_row("b", name="checkout"))
    store.insert_run(run_row("c", name="login"))
    store.set_baseline("a", True)
    store.set_baseline("c", True)
    store.set_baseline("b", True)
    flags = {r["id"]: r["is_baseline"] for r in store.list_runs()[0]}
    assert flags == {"a": False, "b": True, "c": True}
    store.set_baseline("b", False)
    assert store.get_run("b")["is_baseline"] is False


def test_delete_cascades_points(store):
    store.insert_run(run_row("a"))
    store.add_point("a", {"t": 0})
    assert store.delete_run("a") is True
    assert store.delete_run("a") is False
    count = store._db.execute("SELECT COUNT(*) FROM run_points").fetchone()[0]
    assert count == 0


def test_mark_interrupted_only_touches_active_runs(store):
    store.insert_run(run_row("live", status="running"))
    store.insert_run(run_row("done", status="finished"))
    assert store.mark_interrupted(99.0) == 1
    assert store.get_run("live")["status"] == "interrupted"
    assert store.get_run("live")["ended_at"] == 99.0
    assert store.get_run("done")["status"] == "finished"


def test_settings(store):
    assert store.get_setting("limits") is None
    store.put_setting("limits", {"max_vus": 5})
    store.put_setting("limits", {"max_vus": 6})
    assert store.get_setting("limits") == {"max_vus": 6}


def test_data_survives_reopen(tmp_path):
    path = tmp_path / "lp.db"
    s = Store(path)
    s.insert_run(run_row("a"))
    s.close()
    s2 = Store(path)
    assert s2.get_run("a") is not None
    assert s2._db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    s2.close()


def test_refuses_database_from_newer_version(tmp_path):
    path = tmp_path / "lp.db"
    db = sqlite3.connect(path)
    db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    db.close()
    with pytest.raises(RuntimeError, match="newer LoadPilot"):
        Store(path)
