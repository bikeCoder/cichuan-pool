"""验收 #10857：doctor 诊断分层报告——三档分族 + 多落点/无登记单列 + weak 动作提示。"""
from __future__ import annotations

import json
import os

from pool.cli.main import main as cli_main
from pool.core.doctor import doctor_report
from tests.gitfixture import commit, feature_branch_commit, make_repo


def _setup(env):
    """init + 造一个带 main 分支、remote=me/demo 的交付仓（与 env 同项目身份）。"""
    root, _env_proj = env
    os.environ["POOL_DATA_DIR"] = str(root)
    assert cli_main(["init"]) == 0
    proj = make_repo(root.parent / "delivery-proj",
                     remote_url="https://github.com/me/demo.git")
    return root, proj


def _add_next_done(proj, text, sha):
    assert cli_main(["add", text, "--cwd", str(proj)]) == 0
    assert cli_main(["next"]) == 0
    assert cli_main(["done", _last_id(), "--commit", sha]) == 0


def _last_id() -> str:
    import sqlite3
    from pool.store.db import connect
    from pool.store.paths import resolve_db_path
    conn = connect(resolve_db_path(os.environ["POOL_DATA_DIR"]))
    try:
        return str(conn.execute("SELECT MAX(id) FROM tasks").fetchone()[0])
    finally:
        conn.close()


def _force_done_pending_no_sha(text):
    """造「待核账但无登记 sha」件：直接改库（绕过 done 的 sha 必填）。"""
    from pool.store.db import connect
    from pool.store.paths import resolve_db_path
    conn = connect(resolve_db_path(os.environ["POOL_DATA_DIR"]))
    conn.execute("UPDATE tasks SET status='done_pending_merge' WHERE text=?", (text,))
    conn.commit()
    conn.close()


def test_doctor_families_strong_weak_none(env):
    root, proj = _setup(env)
    # strong：已合并到默认分支
    strong_sha = commit(proj, "landed work (#1)")
    _add_next_done(proj, "强件", strong_sha)
    # weak：只在特性分支
    weak_sha = feature_branch_commit(proj)
    _add_next_done(proj, "弱件", weak_sha)
    # none：对象缺失（另一仓的 sha）
    other = make_repo(proj.parent / "other-obj", remote_url="https://github.com/me/demo.git")
    none_sha = commit(other, "elsewhere")
    _add_next_done(proj, "无件", none_sha)

    report = doctor_report(_conn(), probe_repo=str(proj))
    fam = report["families"]
    assert [e["id"] for e in fam["strong"]] == [1]
    assert "default branch" in fam["strong"][0]["reason"]
    assert [e["id"] for e in fam["weak"]] == [2]
    assert [e["id"] for e in fam["none"]] == [3]
    # weak 件必须带「借代理核验 / 人工确认」两个动作提示
    hints = " || ".join(fam["weak"][0]["hints"])
    assert "borrow an agent to verify" in hints
    assert "human confirm" in hints
    # doctor 只读：状态不被归档
    conn = _conn()
    statuses = dict(conn.execute("SELECT id, status FROM tasks").fetchall())
    conn.close()
    assert statuses == {1: "done_pending_merge", 2: "done_pending_merge",
                        3: "done_pending_merge"}


def test_doctor_cross_repo_and_no_sha_families(env):
    root, proj = _setup(env)
    # 多落点/错配：交付登记的 sha 在另一个项目身份的仓
    other = make_repo(proj.parent / "elsewhere", remote_url="https://github.com/other/xyz.git")
    sha = commit(other, "cross work")
    _add_next_done(proj, "错配件", sha)
    # 无登记 sha 件
    assert cli_main(["add", "裸件", "--cwd", str(proj)]) == 0
    assert cli_main(["next"]) == 0
    _force_done_pending_no_sha("裸件")

    report = doctor_report(_conn(), probe_repo=str(other))
    fam = report["families"]
    assert len(fam["cross_repo"]) == 1
    assert "mismatch" in fam["cross_repo"][0]["reason"] or "mismatch" in json.dumps(fam["cross_repo"][0])
    assert len(fam["no_sha"]) == 1
    assert fam["no_sha"][0]["delivery_sha"] is None
    assert report["pending"] == 2 and report["total"] == 2


def test_doctor_cli_json_and_human(env, capsys):
    root, proj = _setup(env)
    sha = commit(proj, "done work (#1)")
    _add_next_done(proj, "已合并件", sha)
    rc = cli_main(["doctor", "--repo", str(proj), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"]
    fam = out["data"]["families"]
    assert [e["id"] for e in fam["strong"]] == [1]
    # 人话输出：分族标题 + 逐件 reason + weak 动作提示
    rc = cli_main(["doctor", "--repo", str(proj)])
    assert rc == 0
    human = capsys.readouterr().out
    assert "strong" in human and "#1" in human


def test_sync_reports_tier_families(env, capsys):
    """sync 输出按三档分族（向后兼容：archived/unconfirmed 保留）。"""
    root, proj = _setup(env)
    weak_sha = feature_branch_commit(proj)
    _add_next_done(proj, "弱件", weak_sha)
    rc = cli_main(["sync", "--repo", str(proj), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["data"]["archived"] == []
    assert out["data"]["unconfirmed"][0]["tier"] == "weak"
    assert out["data"]["families"] == {"strong": [], "weak": [1], "none": []}


def _conn():
    from pool.store.db import connect
    from pool.store.paths import resolve_db_path
    return connect(resolve_db_path(os.environ["POOL_DATA_DIR"]))
