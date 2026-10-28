"""池初始化（design-v1 §3.1）：全新数据根 → 建库建 schema。

返回 (连接, db 路径)。已初始化的库重复 init 是幂等 no-op。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..store import db as store_db
from ..store import backup as store_backup
from ..store.paths import resolve_db_path


def init_pool(data_dir: str | Path | None = None) -> tuple[sqlite3.Connection, Path]:
    db_path = resolve_db_path(data_dir)
    conn = store_db.connect(db_path)
    store_backup.upgrade(conn, db_path=db_path)
    return conn, db_path
