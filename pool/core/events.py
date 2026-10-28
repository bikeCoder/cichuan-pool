"""事件落账：生命周期事件的唯一写入口（design-v1 §3.4 事件行）。"""
from __future__ import annotations

import json
import sqlite3

from .tasks import now_iso


def append_event(conn: sqlite3.Connection, task_id: int, kind: str,
                 payload: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO events (task_id, kind, at, payload_json) VALUES (?, ?, ?, ?)",
        (task_id, kind, now_iso(), json.dumps(payload or {}, ensure_ascii=False)),
    )


def count_events(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
