"""done（交付声明登记）与 sync（交付核账）（design-v1 §1/§4.2/§5.1）。

done 只登记事实；sync 只验证事实。重复 done 同 sha 幂等；重复 sync 不重复归档。
"""
from __future__ import annotations

import re
import sqlite3

from .errors import Code, PoolError
from .model import TaskStatus
from .tasks import _ensure_pool, _row_to_task, now_iso

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def done_task(conn: sqlite3.Connection, task_id: int, sha: str, *, actor: str,
              delivery_repo: str | None = None) -> dict:
    """登记交付声明：claimed → done_pending_merge。

    幂等：已 done_pending_merge/done 且同 sha → no-op 返回现状。
    换 sha 重新声明允许（以最新声明为准），状态不回退。
    """
    _ensure_pool(conn)
    if not isinstance(sha, str) or not _SHA_RE.match(sha.lower()):
        raise PoolError(Code.DELIVERY_SHA_INVALID,
                        f"sha 格式非法：{sha!r}（需 7-40 位十六进制）", {"sha": sha})
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise PoolError(Code.TASK_NOT_FOUND, f"件 #{task_id} 不存在", {"id": task_id})
    task = _row_to_task(row)
    sha_l = sha.lower()
    if task.status is TaskStatus.DONE_PENDING_MERGE:
        if task.delivery_sha == sha_l:
            return {"id": task.id, "status": task.status.value, "idempotent": True}
        # 待核账期换 sha = 以最新声明为准（还没核账，无已归档事实可违反）
        conn.execute(
            "UPDATE tasks SET delivery_sha = ?, delivery_repo = ?, done_at = ? WHERE id = ?",
            (sha_l, delivery_repo or task.project_id, now_iso(), task_id),
        )
        conn.commit()
        return {"id": task.id, "status": task.status.value, "idempotent": False}
    if task.status is not TaskStatus.CLAIMED:
        raise PoolError(Code.TASK_NOT_CLAIMABLE,
                        f"件 #{task_id} 状态为 {task.status.value}，仅 claimed 可 done",
                        {"id": task.id, "status": task.status.value})
    if task.claimed_by != actor:
        raise PoolError(Code.TASK_NOT_CLAIMED_BY_ACTOR,
                        f"件 #{task_id} 由 {task.claimed_by} 认领，非 {actor} 不得 done",
                        {"id": task.id, "claimed_by": task.claimed_by})
    conn.execute(
        "UPDATE tasks SET status = ?, delivery_sha = ?, delivery_repo = ?, done_at = ? WHERE id = ?",
        (TaskStatus.DONE_PENDING_MERGE.value, sha.lower(),
         delivery_repo or task.project_id, now_iso(), task_id),
    )
    from .events import append_event
    append_event(conn, task_id, "done_pending", {"sha": sha.lower(), "actor": actor})
    conn.commit()
    return {"id": task_id, "status": TaskStatus.DONE_PENDING_MERGE.value, "idempotent": False}


def sync_pool(conn: sqlite3.Connection, *, probe_repo: str,
              evidence_probe=None) -> dict:
    """对全部 done_pending_merge 逐件核账（design-v1 §4.2 归档准入）。

    逐件降级：单件探测异常不影响其他件，只进「待确认」组并带原因。
    返回 {archived: [...], unconfirmed: [...]}；有环境级失败时附带 errors。
    """
    _ensure_pool(conn)
    if evidence_probe is None:
        from ..evidence.adapters.git import probe as evidence_probe
    archived, unconfirmed, errors = [], [], []
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status = ? ORDER BY id",
        (TaskStatus.DONE_PENDING_MERGE.value,),
    ).fetchall()
    for row in rows:
        task = _row_to_task(row)
        try:
            ev = evidence_probe(probe_repo, task.delivery_sha,
                                project_id=task.project_id)
        except Exception as exc:  # 逐件降级，不整批失败
            unconfirmed.append({"id": task.id, "tier": "none",
                                "reason": f"探测异常：{exc}"})
            continue
        from ..evidence.base import can_auto_archive
        entry = {"id": task.id, "sha": task.delivery_sha, **ev.to_dict()}
        if can_auto_archive(ev):
            conn.execute(
                "UPDATE tasks SET status = ?, archived_at = ? WHERE id = ? AND status = ?",
                (TaskStatus.DONE.value, now_iso(), task.id,
                 TaskStatus.DONE_PENDING_MERGE.value),
            )
            from .events import append_event
            append_event(conn, task.id, "archived",
                         {"sha": task.delivery_sha, "tier": ev.tier.value})
            archived.append(entry)
        else:
            unconfirmed.append(entry)
    conn.commit()
    return {"archived": archived, "unconfirmed": unconfirmed, "errors": errors}
