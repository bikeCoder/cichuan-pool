"""验收：旧 fixture 可升级；迁移失败可从备份恢复。"""
from __future__ import annotations

import sqlite3

import pytest

from pool.core.model import PUBLIC_COLUMNS
from pool.store import backup as store_backup
from pool.store import db as store_db
from pool.store import migrations as store_migrations
from pool.store.backup import MigrationError


def _make_legacy_fixture(db_path, version=0):
    """模拟一个旧版本库：只有 legacy 表 + user_version=N。"""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE legacy_tasks (id INTEGER PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO legacy_tasks VALUES (1, 'old item')")
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    return conn


def test_legacy_fixture_upgrades_to_current(data_dir, tmp_path):
    db_path = data_dir / "pool.db"
    _make_legacy_fixture(db_path)
    conn = store_db.connect(db_path)

    # 注册一个 v0 → v1 迁移：把 legacy 数据搬进 tasks 表
    @store_migrations.register(0)
    def _v0_to_v1(conn):
        cols = ",\n  ".join(f"{n} {d}" for n, d in PUBLIC_COLUMNS.items())
        conn.executescript(f"""
            CREATE TABLE tasks ({cols});
            INSERT INTO tasks (id, project_id, text, status, created_at)
              SELECT id, 'default', title, 'candidate', '2026-01-01T00:00:00'
              FROM legacy_tasks;
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES ('schema_version', '1');
            DROP TABLE legacy_tasks;
        """)

    try:
        final = store_backup.upgrade(conn, db_path=db_path)
        assert final == store_db.SCHEMA_VERSION
        row = conn.execute("SELECT id, project_id, text FROM tasks").fetchone()
        assert (row["id"], row["project_id"], row["text"]) == (1, "default", "old item")
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='legacy_tasks'"
        ).fetchone()
    finally:
        store_migrations._STEPS.pop(0, None)


def test_failed_migration_restores_backup(data_dir):
    db_path = data_dir / "pool.db"
    _make_legacy_fixture(db_path)
    conn = store_db.connect(db_path)
    before_bytes = db_path.read_bytes()

    @store_migrations.register(0)
    def _boom(conn):
        conn.execute("CREATE TABLE half_written (x INTEGER)")
        raise RuntimeError("模拟迁移中途崩溃")

    try:
        with pytest.raises(MigrationError, match="restored from backup"):
            store_backup.upgrade(conn, db_path=db_path)
    finally:
        store_migrations._STEPS.pop(0, None)

    # 原库文件恢复为迁移前内容（half_written 不存在）
    fresh = sqlite3.connect(db_path)
    names = {r[0] for r in fresh.execute("SELECT name FROM sqlite_master")}
    assert "legacy_tasks" in names
    assert "half_written" not in names
    assert store_db.schema_version(fresh) == 0
    assert db_path.read_bytes() == before_bytes


def test_future_schema_version_is_rejected(data_dir, tmp_path):
    db_path = data_dir / "pool.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (x)")
    conn.execute(f"PRAGMA user_version = {store_db.SCHEMA_VERSION + 5}")
    conn.commit()

    with pytest.raises(MigrationError, match="newer than supported"):
        store_backup.upgrade(conn, db_path=db_path)
