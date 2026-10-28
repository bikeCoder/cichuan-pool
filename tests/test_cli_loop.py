"""验收 #10847：干净项目 init/add/next；稳定出队；幂等；错误码。"""
from __future__ import annotations

import json
import subprocess

import pytest

from pool.cli.main import main as cli_main
from pool.core import tasks as ops
from pool.core.errors import Code, PoolError
from pool.store.paths import ENV_DATA_DIR


@pytest.fixture
def env(monkeypatch, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv(ENV_DATA_DIR, str(root))
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    subprocess.run(["git", "-C", str(proj), "remote", "add", "origin",
                    "https://github.com/me/demo.git"], check=True)
    return root, proj


def _cli(*argv, expect=0):
    rc = cli_main(list(argv))
    assert rc == expect, f"exit {rc} != {expect} for {argv}"
    return rc


def _run_json(*argv, expect=0):
    """跑 CLI 并解析 JSON envelope（--json 可放任意位置）。"""
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli_main([*argv])
    out = buf.getvalue().strip().splitlines()[-1]
    return rc, json.loads(out)


def test_clean_project_init_add_next(env):
    _, proj = env
    _cli("--json", "init")
    rc, env_ok = _run_json("--json", "add", "第一件事", "--cwd", str(proj))
    assert rc == 0 and env_ok["ok"] and env_ok["data"]["id"] == 1
    rc, nxt = _run_json("--json", "next")
    assert rc == 0
    assert nxt["data"]["task"]["id"] == 1
    assert "理由" not in json.dumps(nxt)  # reason 在 data 里是结构化字段
    assert nxt["data"]["reason"]


def test_next_ordering_score_then_age_then_id(env):
    _, proj = env
    _cli("init")
    ids = []
    for text in ("甲", "乙", "丙"):
        rc, r = _run_json("--json", "add", text, "--cwd", str(proj))
        ids.append(r["data"]["id"])
    conn = __import__("pool.store.db", fromlist=["connect"]).connect()
    conn.execute("UPDATE tasks SET score_json = ? WHERE id = ?", (json.dumps({"score": 5}), ids[2]))
    conn.commit(); conn.close()
    rc, nxt = _run_json("--json", "next")
    assert nxt["data"]["task"]["id"] == ids[2]  # 评分优先
    assert "评分最高" in nxt["data"]["reason"]


def test_same_score_ties_break_by_age_then_id(env):
    """两件同分任务按年龄和件号稳定出队。"""
    _, proj = env
    _cli("init")
    rcs = [_run_json("--json", "add", t, "--cwd", str(proj))[1] for t in ("甲", "乙")]
    a, b = rcs[0]["data"]["id"], rcs[1]["data"]["id"]
    conn = __import__("pool.store.db", fromlist=["connect"]).connect()
    conn.execute("UPDATE tasks SET score_json=? WHERE id=?", (json.dumps({"score": 9}), a))
    conn.execute("UPDATE tasks SET score_json=? WHERE id=?", (json.dumps({"score": 9}), b))
    # 同分下让乙更早创建（默认同拍创建时件号序=年龄序，需显式错开才测得出年龄优先）
    conn.execute("UPDATE tasks SET created_at='2026-01-01T00:00:00.000Z' WHERE id=?", (b,))
    conn.execute("UPDATE tasks SET created_at='2026-01-02T00:00:00.000Z' WHERE id=?", (a,))
    conn.commit(); conn.close()
    rc, nxt = _run_json("--json", "next")
    assert nxt["data"]["task"]["id"] == b  # 同分取先创建（年龄大者）
    # 乙办结（进入待核账）后再领，轮到甲——同分确定序下最老者持续优先
    conn = __import__("pool.store.db", fromlist=["connect"]).connect()
    conn.execute("UPDATE tasks SET status='done_pending_merge' WHERE id=?", (b,))
    conn.commit(); conn.close()
    rc, nxt2 = _run_json("--json", "next")
    assert nxt2["data"]["task"]["id"] == a


def test_repeated_next_does_not_double_claim(env):
    _, proj = env
    _cli("init")
    _run_json("--json", "add", "唯一一件", "--cwd", str(proj))
    rc, first = _run_json("--json", "next")
    assert first["ok"]
    rc, second = _run_json("--json", "next", expect=3)
    assert second["ok"] is False
    assert second["error"]["code"] == Code.TASK_ALREADY_CLAIMED.value
    assert second["error"]["details"]["claimed_task_id"] == first["data"]["task"]["id"]


def test_error_codes_documented(env):
    root, proj = env
    # 未初始化 → 4 档
    rc, err = _run_json("--json", "next", expect=4)
    assert err["error"]["code"] == Code.POOL_NOT_INITIALIZED.value
    _cli("init")
    # 空池 → 3 档
    rc, err = _run_json("--json", "next", expect=3)
    assert err["error"]["code"] == Code.POOL_EMPTY.value
    # 重复 init → 3 档已初始化
    rc, err = _run_json("--json", "init", expect=3)
    assert err["error"]["code"] == Code.POOL_ALREADY_INITIALIZED.value
    # 非 git 目录 add → 项目无法识别
    bare = root.parent / "bare"
    bare.mkdir()
    rc, err = _run_json("--json", "add", "x", "--cwd", str(bare), expect=3)
    assert err["error"]["code"] == Code.PROJECT_UNRESOLVED.value
    # TASK_NOT_FOUND 走 core 面
    conn = __import__("pool.store.db", fromlist=["connect"]).connect()
    with pytest.raises(PoolError) as ei:
        ops.get_task(conn, 999)
    assert ei.value.code == Code.TASK_NOT_FOUND
    conn.close()


def test_tag_filter_narrows_not_reorders(env):
    _, proj = env
    _cli("init")
    _run_json("--json", "add", "无标", "--cwd", str(proj))
    rc, r = _run_json("--json", "add", "带标", "--cwd", str(proj), "--tag", "ui")
    # 无 WIP 时：过滤无命中 → 可认领件为空（而非空池）
    rc, err = _run_json("--json", "next", "--tag", "nope", expect=3)
    assert err["error"]["code"] == Code.TASK_NOT_CLAIMABLE.value
    conn = __import__("pool.store.db", fromlist=["connect"]).connect()
    conn.close()
    rc, nxt = _run_json("--json", "next", "--tag", "ui")
    assert nxt["data"]["task"]["text"] == "带标"


def test_human_output_and_exit_codes(env, capsys):
    _, proj = env
    assert cli_main(["init"]) == 0
    assert "池已就绪" in capsys.readouterr().out
    assert cli_main(["add", "事情", "--cwd", str(proj)]) == 0
    assert "#1 已入池" in capsys.readouterr().out
    assert cli_main(["next"]) == 0
    out = capsys.readouterr().out
    assert "认领 #1" in out and "理由：" in out
    # 未初始化的另一个根 → 退出码 4
    import os
    old = os.environ.get(ENV_DATA_DIR)
    os.environ[ENV_DATA_DIR] = str(proj.parent / "other-root")
    try:
        assert cli_main(["next"]) == 4
        assert "POOL_NOT_INITIALIZED" in capsys.readouterr().err
    finally:
        if old:
            os.environ[ENV_DATA_DIR] = old
        else:
            os.environ.pop(ENV_DATA_DIR, None)


def test_json_flag_accepted_in_any_position(env):
    """全局参数前/后置都可用（agent 习惯后置写法）。"""
    _, proj = env
    _cli("init")
    rc, r = _run_json("--json", "add", "甲", "--cwd", str(proj))
    assert r["ok"]
    rc, r2 = _run_json("add", "乙", "--cwd", str(proj), "--json")
    assert r2["ok"] and r2["data"]["id"] == 2
    rc, nxt = _run_json("next", "--json")
    assert nxt["ok"] and nxt["data"]["task"]["id"] == 1
