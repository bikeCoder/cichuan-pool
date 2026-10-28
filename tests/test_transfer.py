"""验收 #10849：导出重导入对账 / 版本报错 / 冲突不覆盖 / untrusted 基线。"""
from __future__ import annotations

import json
import sqlite3

import pytest

from pool import FORMAT_NAME, FORMAT_VERSION
from pool.board.config import DEFAULT_HOST, resolve_bind
from pool.core import tasks as ops
from pool.core.errors import Code, PoolError
from pool.core.transfer import export_pool, import_pool
from pool.cli.main import main as cli_main
from pool.store import db as store_db
from pool.store.paths import resolve_db_path


@pytest.fixture
def pool_with_data(env):
    """init + 3 件（含 next/done 生命周期）→ (conn, 根)。"""
    root, proj = env
    conn = store_db.connect(resolve_db_path(root))
    ops.init_pool_cmd(root)
    for text in ("甲", "乙", "丙"):
        ops.add_task(conn, text, project_id="github.com/me/demo")
    claimed, _ = ops.next_task(conn, actor="solo")
    yield conn, root
    conn.close()


def test_roundtrip_counts_reconcile(pool_with_data, tmp_path):
    conn, root = pool_with_data
    dump = tmp_path / "dump.jsonl"
    exp = export_pool(conn, dump)
    assert exp["tasks"] == 3 and exp["events"] >= 3

    # 导入进全新池
    import subprocess
    other_root = tmp_path / "root2"
    other_root.mkdir()
    conn2 = store_db.connect(other_root / "pool.db")
    ops.init_pool_cmd(other_root)
    rep = import_pool(conn2, dump)
    assert rep["tasks"]["added"] == 3
    assert rep["tasks"]["conflict"] == 0
    assert rep["events"]["added"] == exp["events"]
    # 计数对账：任务数与事件数一致
    assert conn2.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"] == exp["tasks"]
    assert conn2.execute("SELECT COUNT(*) c FROM events").fetchone()["c"] == exp["events"]
    # 内容对账：除 untrusted 外字段逐列一致（外部导入强制 untrusted=1，见下一测试）
    for row_src, row_dst in zip(conn.execute("SELECT * FROM tasks ORDER BY id"),
                                conn2.execute("SELECT * FROM tasks ORDER BY id")):
        src = {k: row_src[k] for k in row_src.keys() if k != "untrusted"}
        dst = {k: row_dst[k] for k in row_dst.keys() if k != "untrusted"}
        assert src == dst
    conn2.close()


def test_import_marks_external_untrusted(tmp_path, pool_with_data):
    conn, root = pool_with_data
    dump = tmp_path / "dump.jsonl"
    export_pool(conn, dump)
    other_root = tmp_path / "r2"
    other_root.mkdir()
    conn2 = store_db.connect(other_root / "pool.db")
    ops.init_pool_cmd(other_root)
    import_pool(conn2, dump)
    # D9：外部导入一律 untrusted（即便导出时是可信件）
    flags = [r[0] for r in conn2.execute("SELECT untrusted FROM tasks")]
    assert flags == [1, 1, 1]
    conn2.close()


def test_unsupported_version_rejected(tmp_path, pool_with_data):
    conn, _ = pool_with_data
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"format": FORMAT_NAME, "version": 99}) + "\n",
                   encoding="utf-8")
    with pytest.raises(PoolError) as ei:
        import_pool(conn, bad)
    assert ei.value.code is Code.IMPORT_FORMAT_UNSUPPORTED
    # 格式名不对同样拒
    bad2 = tmp_path / "bad2.jsonl"
    bad2.write_text(json.dumps({"format": "other-tool", "version": 1}) + "\n",
                    encoding="utf-8")
    with pytest.raises(PoolError) as ei2:
        import_pool(conn, bad2)
    assert ei2.value.code is Code.IMPORT_FORMAT_UNSUPPORTED


def test_id_conflict_never_overwrites(tmp_path, pool_with_data):
    conn, root = pool_with_data
    dump = tmp_path / "dump.jsonl"
    export_pool(conn, dump)
    # 对同一池再导：全部 ID 冲突
    rep = import_pool(conn, dump)
    assert rep["tasks"]["conflict"] == 3 and rep["tasks"]["added"] == 0
    # 原内容未被覆盖（text 仍是 甲/乙/丙）
    texts = [r[0] for r in conn.execute("SELECT text FROM tasks ORDER BY id")]
    assert texts == ["甲", "乙", "丙"]
    assert all(c["reason"] for c in rep["tasks"]["conflicts"])


def test_untrusted_marked_readonly_in_next_output(env, capsys):
    root, proj = env
    assert cli_main(["init"]) == 0
    assert cli_main(["add", "外部件", "--cwd", str(proj), "--untrusted"]) == 0
    capsys.readouterr()
    assert cli_main(["next", "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out["data"]["task"]["untrusted"] is True
    assert out["data"]["untrusted_readonly"] is True
    assert "只读" in out["data"]["note"]
    # 人话输出同样显式
    conn = store_db.connect(resolve_db_path(root))
    conn.execute("UPDATE tasks SET status='candidate', claimed_by=NULL WHERE id=1")
    conn.commit(); conn.close()
    assert cli_main(["next"]) == 0
    out_line = capsys.readouterr().out
    assert "untrusted" in out_line and "只读" in out_line


def test_board_binds_localhost_by_default():
    host, exposed = resolve_bind()
    assert host == DEFAULT_HOST == "127.0.0.1"
    assert exposed is False
    host2, exposed2 = resolve_bind("0.0.0.0")
    assert exposed2 is True  # 显式暴露必须可识别（调用方负责告警）


def test_schema_v2_migration_backfills_events(tmp_path):
    """v1 老库（有 tasks 无 events）升级后每件补一条 imported 事件。"""
    db_path = tmp_path / "v1.db"
    conn = sqlite3.connect(db_path)
    from pool.core.model import PUBLIC_COLUMNS
    cols = ",\n  ".join(f"{n} {d}" for n, d in PUBLIC_COLUMNS.items())
    conn.executescript(f"""
        CREATE TABLE tasks ({cols});
        INSERT INTO tasks (id, project_id, text, status, created_at)
          VALUES (1, 'p', '旧件', 'candidate', '2026-01-01T00:00:00Z');
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        PRAGMA user_version = 1;
    """)
    conn.commit(); conn.close()
    conn = store_db.connect(db_path)
    from pool.store.backup import upgrade
    assert upgrade(conn, db_path=db_path) == 2
    assert store_db.schema_version(conn) == 2
    assert conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"] == 1
    conn.close()


def test_export_import_via_cli(env, tmp_path, capsys):
    root, proj = env
    dump = tmp_path / "cli.jsonl"
    assert cli_main(["init"]) == 0
    assert cli_main(["add", "经CLI", "--cwd", str(proj)]) == 0
    capsys.readouterr()
    assert cli_main(["export", str(dump)]) == 0
    assert "1 件任务" in capsys.readouterr().out
    # 重导回同一池 → 冲突报告（不覆盖）
    rc = cli_main(["import", str(dump)])
    assert rc == 0
    assert "冲突 1" in capsys.readouterr().out
