"""验收：全新数据根可初始化；schema 与公开字段契约一致。"""
from __future__ import annotations

from pool.core.init_pool import init_pool
from pool.core.model import FORBIDDEN_COLUMNS, PUBLIC_COLUMNS, TaskStatus, TRANSITIONS
from pool.store import db as store_db


def test_fresh_data_root_initializes(data_dir):
    conn, path = init_pool(data_dir)
    assert path.exists()
    assert store_db.schema_version(conn) == store_db.SCHEMA_VERSION
    # WAL 生效
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_init_is_idempotent(data_dir):
    conn1, _ = init_pool(data_dir)
    conn1.close()
    conn2, path2 = init_pool(data_dir)
    assert store_db.schema_version(conn2) == store_db.SCHEMA_VERSION
    assert conn2.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == 0


def test_schema_columns_match_public_contract(data_dir):
    conn, _ = init_pool(data_dir)
    cols = store_db.task_columns(conn)
    assert cols == set(PUBLIC_COLUMNS)


def test_schema_has_no_internal_fields(data_dir):
    conn, _ = init_pool(data_dir)
    cols = store_db.task_columns(conn)
    leaked = cols & FORBIDDEN_COLUMNS
    assert not leaked, f"内部字段漏进公开 schema：{sorted(leaked)}"
