"""SQLite storage for runs, their per-second points, and settings.

Uses the standard-library sqlite3 module: the schema is small, and avoiding an ORM keeps
the install light. Writes are tiny (one row per second of a run), so they run inline on
the event loop; a lock makes the shared connection safe if another thread touches it.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

# Each entry upgrades the schema by one version (tracked in PRAGMA user_version).
# Never edit a released migration; append a new one.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE runs (
        id             TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        status         TEXT NOT NULL,
        mode           TEXT NOT NULL,
        plan           TEXT NOT NULL,
        total_duration REAL NOT NULL,
        elapsed        REAL NOT NULL DEFAULT 0,
        created_at     REAL NOT NULL,
        started_at     REAL,
        ended_at       REAL,
        error          TEXT,
        summary        TEXT,
        events         TEXT NOT NULL DEFAULT '[]',
        notes          TEXT NOT NULL DEFAULT '',
        is_baseline    INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX runs_created ON runs (created_at DESC);
    CREATE INDEX runs_name ON runs (name);
    CREATE TABLE run_points (
        run_id TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
        t      INTEGER NOT NULL,
        point  TEXT NOT NULL,
        PRIMARY KEY (run_id, t)
    );
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]

_JSON_COLUMNS = ("plan", "summary", "events")
_UPDATABLE = {
    "name",
    "status",
    "elapsed",
    "started_at",
    "ended_at",
    "error",
    "summary",
    "events",
    "notes",
}


def default_db_path() -> Path:
    return Path.home() / ".loadpilot" / "loadpilot.db"


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _migrate(self) -> None:
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise RuntimeError(
                    f"database {self.path} was created by a newer LoadPilot "
                    f"(schema {version}, this version knows {len(MIGRATIONS)})"
                )
            for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                self._db.executescript(f"BEGIN; {sql}; PRAGMA user_version = {i}; COMMIT;")

    # ---- runs -------------------------------------------------------------

    def insert_run(self, run: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO runs (id, name, status, mode, plan, total_duration, created_at)
                   VALUES (:id, :name, :status, :mode, :plan, :total_duration, :created_at)""",
                {**run, "plan": json.dumps(run["plan"])},
            )

    def update_run(self, run_id: str, **fields: Any) -> None:
        unknown = set(fields) - _UPDATABLE
        if unknown:
            raise ValueError(f"can't update {sorted(unknown)}")
        if not fields:
            return
        values = {k: json.dumps(v) if k in _JSON_COLUMNS else v for k, v in fields.items()}
        assignments = ", ".join(f"{k} = :{k}" for k in values)
        with self._lock:
            self._db.execute(
                f"UPDATE runs SET {assignments} WHERE id = :_id", {**values, "_id": run_id}
            )

    def add_point(self, run_id: str, point: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO run_points (run_id, t, point) VALUES (?, ?, ?)",
                (run_id, point["t"], json.dumps(point)),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            points = self._db.execute(
                "SELECT point FROM run_points WHERE run_id = ? ORDER BY t", (run_id,)
            ).fetchall()
        run = _row(row)
        run["series"] = [json.loads(p["point"]) for p in points]
        return run

    def list_runs(
        self, *, q: str = "", limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        where, params = "", []
        if q:
            where = "WHERE name LIKE ? ESCAPE '\\'"
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        with self._lock:
            total = self._db.execute(f"SELECT COUNT(*) FROM runs {where}", params).fetchone()[0]
            rows = self._db.execute(
                f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return [_row(r) for r in rows], int(total)

    def delete_run(self, run_id: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        return cur.rowcount > 0

    def set_baseline(self, run_id: str, on: bool) -> None:
        """A baseline is per test name: marking one clears the others with that name."""
        with self._lock:
            self._db.execute("BEGIN")
            if on:
                self._db.execute(
                    "UPDATE runs SET is_baseline = 0 "
                    "WHERE name = (SELECT name FROM runs WHERE id = ?)",
                    (run_id,),
                )
            self._db.execute(
                "UPDATE runs SET is_baseline = ? WHERE id = ?", (1 if on else 0, run_id)
            )
            self._db.execute("COMMIT")

    def mark_interrupted(self, now: float) -> int:
        """Runs still marked active belong to a server that stopped mid-run."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE runs SET status = 'interrupted', ended_at = COALESCE(ended_at, ?) "
                "WHERE status IN ('pending', 'running', 'paused', 'stopping')",
                (now,),
            )
        return cur.rowcount

    # ---- settings ---------------------------------------------------------

    def get_setting(self, key: str) -> Any:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return None if row is None else json.loads(row["value"])

    def put_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )


def _row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for col in _JSON_COLUMNS:
        if data.get(col) is not None:
            data[col] = json.loads(data[col])
    data["is_baseline"] = bool(data["is_baseline"])
    return data
