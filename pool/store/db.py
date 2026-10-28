"""SQLite 连接与 schema（design-v1 §3）。

schema 演化纪律：只允许追加迁移（migrations 列表），不允许改历史迁移；
schema_version 存 PRAGMA user_version（1 起步，0 = 未初始化空库）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..core.model import PUBLIC_COLUMNS
from .paths import resolve_db_path

SCHEMA_VERSION = 2


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else resolve_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    cols = ",\n  ".join(f"{name} {decl}" for name, decl in PUBLIC_COLUMNS.items())
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS tasks (
          {cols}
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY,
          task_id INTEGER NOT NULL,
          kind TEXT NOT NULL,
          at TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{{}}'
        );
        CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
        """
    )
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def task_columns(conn: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
