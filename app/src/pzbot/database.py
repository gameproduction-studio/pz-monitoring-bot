from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    save_signature TEXT NOT NULL UNIQUE,
    physical_items INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    item_id TEXT,
    full_type TEXT,
    event_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_item_id ON events(item_id);
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class StateDatabase:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def latest_snapshot(self) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT snapshot_json FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def latest_signature(self) -> str | None:
        row = self.connection.execute("SELECT save_signature FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        return str(row[0]) if row else None

    def store(self, *, created_at: str, signature: str, snapshot: dict[str, Any], events: list[dict[str, Any]], physical_items: int) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO snapshots(created_at, save_signature, physical_items, snapshot_json) VALUES(?,?,?,?)",
                (created_at, signature, physical_items, json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))),
            )
            snapshot_id = int(cursor.lastrowid)
            self.connection.executemany(
                "INSERT INTO events(snapshot_id, created_at, kind, item_id, full_type, event_json) VALUES(?,?,?,?,?,?)",
                [
                    (snapshot_id, event["time"], event["kind"], event.get("itemId"), event.get("fullType"), json.dumps(event, ensure_ascii=False, separators=(",", ":")))
                    for event in events
                ],
            )
        return snapshot_id

    def recent_events(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT event_json FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def snapshot_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])

