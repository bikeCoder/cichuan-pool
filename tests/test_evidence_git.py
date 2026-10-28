"""对抗测试（design-v1 §4.4）：六情形 + 归档准入 + 谎报即失败。

漏报判级说明：游离提交判 none 属「漏报 strong 为 weak/none 允许」，理由在 reason。
"""
from __future__ import annotations

import pytest

from pool.core import tasks as ops
from pool.core.delivery import done_task, sync_pool
from pool.core.errors import Code, PoolError
from pool.evidence.adapters.git import probe
from pool.evidence.base import Tier, can_auto_archive

from tests.gitfixture import commit, dangling_commit, feature_branch_commit, make_repo

PROJECT = "github.com/me/demo"


@pytest.fixture
def pooled(env):
    """已 init、已 add 一件并 next 认领的池。"""
    from pool.cli.main import main as _  # noqa: F401 确保 cli 可导入
    root, proj = env
    cli_init = __import__("pool.core.tasks", fromlist=["init_pool_cmd"])
    from pool.store import db as store_db
    from pool.store.paths import resolve_db_path
    conn = store_db.connect(resolve_db_path(root))
    cli_init.init_pool_cmd(root)
    ops.add_task(conn, "做一件事", project_id=PROJECT)
    claimed, reason = ops.next_task(conn, actor="solo")
    return conn, claimed.id


def test_merged_on_default_branch_is_strong(tmp_path, pooled):
    conn, tid = pooled
    repo = make_repo(tmp_path / "repo")
    sha = commit(repo, "work")
    ev = probe(repo, sha, project_id=PROJECT)
    assert ev.tier is Tier.STRONG and ev.delivered is True
    assert can_auto_archive(ev)


def test_unmerged_dangling_is_not_strong(tmp_path, pooled):
    conn, tid = pooled
    repo = make_repo(tmp_path / "repo")
    sha = dangling_commit(repo)
    ev = probe(repo, sha, project_id=PROJECT)
    assert ev.tier is not Tier.STRONG or ev.delivered is not True  # 谎报即失败
    assert ev.tier is Tier.NONE and not can_auto_archive(ev)


def test_feature_branch_only_is_weak(tmp_path, pooled):
    conn, tid = pooled
    repo = make_repo(tmp_path / "repo")
    sha = feature_branch_commit(repo)
    ev = probe(repo, sha, project_id=PROJECT)
    assert ev.tier is Tier.WEAK
    assert not can_auto_archive(ev)


def test_missing_sha_is_none(tmp_path):
    repo = make_repo(tmp_path / "repo")
    ev = probe(repo, None, project_id=PROJECT)
    assert ev.tier is Tier.NONE and not can_auto_archive(ev)


def test_missing_object_is_none(tmp_path):
    repo = make_repo(tmp_path / "repo")
    ev = probe(repo, "deadbeef" * 5, project_id=PROJECT)
    assert ev.tier is Tier.NONE and not can_auto_archive(ev)


def test_project_mismatch_never_archives(tmp_path):
    repo = make_repo(tmp_path / "repo", remote_url="https://github.com/other/xyz.git")
    sha = commit(repo, "work")
    ev = probe(repo, sha, project_id=PROJECT)
    assert ev.project_mismatch is True
    assert not can_auto_archive(ev)  # 恒拒，即使 commit 真实存在


def test_probe_is_readonly(tmp_path):
    """探测不 fetch、不改 ref、不写工作区。"""
    repo = make_repo(tmp_path / "repo")
    commit(repo, "work")
    before_refs = subprocess_refs(repo)
    (repo / "a.txt").write_text("1", encoding="utf-8")
    before_tree = (repo / "a.txt").read_text(encoding="utf-8")
    probe(repo, "HEAD", project_id=PROJECT)
    assert subprocess_refs(repo) == before_refs
    assert (repo / "a.txt").read_text(encoding="utf-8") == before_tree


def subprocess_refs(repo):
    import subprocess
    r = subprocess.run(["git", "-C", str(repo), "show-ref"],
                       capture_output=True, text=True)
    return r.stdout


def test_done_then_sync_archives_strong(tmp_path, pooled, env):
    conn, tid = pooled
    root, proj = env
    repo = make_repo(root / "delivery")
    sha = commit(repo, "the work")
    # 认领者本人声明交付
    result = done_task(conn, tid, sha, actor="solo")
    assert result["status"] == "done_pending_merge"
    # 核账：交付仓身份与任务项目一致 → 自动归档
    out = sync_pool(conn, probe_repo=str(repo))
    assert [e["id"] for e in out["archived"]] == [tid]
    row = conn.execute("SELECT status, archived_at FROM tasks WHERE id=?", (tid,)).fetchone()
    assert row["status"] == "done" and row["archived_at"]
    # 重复 sync 不重复归档、无重复输出
    out2 = sync_pool(conn, probe_repo=str(repo))
    assert out2["archived"] == [] and out2["unconfirmed"] == []


def test_sync_weak_stays_pending(tmp_path, pooled, env):
    conn, tid = pooled
    root, proj = env
    repo = make_repo(root / "delivery")
    sha = feature_branch_commit(repo)
    done_task(conn, tid, sha, actor="solo")
    out = sync_pool(conn, probe_repo=str(repo))
    assert out["archived"] == []
    assert out["unconfirmed"][0]["tier"] == "weak"
    assert conn.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "done_pending_merge"


def test_run_active_does_not_veto_strong(tmp_path, pooled, env):
    """owner/actor 是否活跃不是件级事实，不否决 strong（§4.2）。"""
    conn, tid = pooled
    root, proj = env
    repo = make_repo(root / "delivery")
    sha = commit(repo, "merged work")
    done_task(conn, tid, sha, actor="solo")
    # 模拟「run 活跃」：再开一件处于 claimed 状态
    ops.add_task(conn, "另一件在办", project_id=PROJECT)
    conn.execute("UPDATE tasks SET status='claimed', claimed_by='solo' WHERE text='另一件在办'")
    conn.commit()
    out = sync_pool(conn, probe_repo=str(repo))
    assert [e["id"] for e in out["archived"]] == [tid]  # strong 不被在办件否决


def test_done_idempotent_same_sha(tmp_path, pooled):
    conn, tid = pooled
    sha = "abc1234"
    r1 = done_task(conn, tid, sha, actor="solo")
    r2 = done_task(conn, tid, sha, actor="solo")
    assert r2["idempotent"] is True


def test_done_different_sha_redeclares(tmp_path, pooled):
    conn, tid = pooled
    done_task(conn, tid, "abc1234", actor="solo")
    r = done_task(conn, tid, "def5678", actor="solo")
    assert r["idempotent"] is False
    assert conn.execute("SELECT delivery_sha FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "def5678"


def test_done_guards(tmp_path, pooled):
    conn, tid = pooled
    with pytest.raises(PoolError) as ei:
        done_task(conn, tid, "ZZZ!", actor="solo")
    assert ei.value.code is Code.DELIVERY_SHA_INVALID
    with pytest.raises(PoolError) as ei:
        done_task(conn, tid, "abc1234", actor="someone-else")
    assert ei.value.code is Code.TASK_NOT_CLAIMED_BY_ACTOR
    done_task(conn, tid, "abc1234", actor="solo")
    # 待核账期换 sha = 以最新声明为准，允许
    r = done_task(conn, tid, "def5678", actor="solo")
    assert r["idempotent"] is False
    # done 终态拒绝再 done
    conn.execute("UPDATE tasks SET status='done', archived_at='2026-01-01' WHERE id=?", (tid,))
    conn.commit()
    with pytest.raises(PoolError) as ei2:
        done_task(conn, tid, "aaa0000", actor="solo")
    assert ei2.value.code is Code.TASK_NOT_CLAIMABLE
