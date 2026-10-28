"""schema 迁移注册表：v(n) → v(n+1) 的逐步迁移。

纪律：迁移只追加不改写；每步必须幂等失败安全（失败即整体回滚到备份）。
V1 起步库直接由 create_schema 建到 SCHEMA_VERSION，这里预留演化通道。
"""
from __future__ import annotations

import sqlite3
from typing import Callable

Step = Callable[[sqlite3.Connection], None]

_STEPS: dict[int, Step] = {}


def get_step(version: int) -> Step | None:
    """返回把 v`version` 迁到 v`version+1` 的步骤。"""
    return _STEPS.get(version)


def register(from_version: int) -> Callable[[Step], Step]:
    def deco(fn: Step) -> Step:
        _STEPS[from_version] = fn
        return fn
    return deco


@register(1)
def v1_to_v2(conn: sqlite3.Connection) -> None:
    """v2 新增事件表；存量任务各补一条 imported 起始事件，保证导出计数可对账。"""
    conn.executescript(
        """
        CREATE TABLE events (
          id INTEGER PRIMARY KEY,
          task_id INTEGER NOT NULL,
          kind TEXT NOT NULL,
          at TEXT NOT NULL,
          payload_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX idx_events_task ON events(task_id);
        INSERT INTO events (task_id, kind, at, payload_json)
          SELECT id, 'imported', created_at, '{}' FROM tasks;
        """
    )
