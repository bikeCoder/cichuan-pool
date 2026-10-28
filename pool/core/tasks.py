"""核心闭环操作：init / add / next（design-v1 §5.1-§5.2）。

next 的原子性：BEGIN IMMEDIATE 下选件+改状态一步提交，两个并发 next
不可能拿到同一件。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone

from ..store import db as store_db
from ..store.backup import MigrationError
from .errors import Code, PoolError
from .model import PUBLIC_COLUMNS, Task, TaskStatus, can_transition


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _ensure_pool(conn: sqlite3.Connection) -> None:
    v = store_db.schema_version(conn)
    if v == 0 or not store_db.task_columns(conn):
        raise PoolError(Code.POOL_NOT_INITIALIZED, "pool is not initialized: run `pool init` first")


def init_pool_cmd(data_dir=None) -> dict:
    """pool init。已初始化 → POOL_ALREADY_INITIALIZED（幂等失败=业务拒绝）。"""
    from .init_pool import init_pool

    db_path_guess = store_db.resolve_db_path(data_dir)
    if db_path_guess.exists() and db_path_guess.stat().st_size > 0:
        probe = store_db.connect(db_path_guess)
        try:
            if store_db.schema_version(probe) == store_db.SCHEMA_VERSION:
                raise PoolError(
                    Code.POOL_ALREADY_INITIALIZED,
                    f"pool already initialized: {db_path_guess}",
                    details={"data_dir": str(db_path_guess.parent)},
                )
        except store_db.sqlite3.DatabaseError:
            pass
        finally:
            probe.close()
    conn, path = init_pool(data_dir)
    return {"data_dir": str(path.parent), "db_path": str(path)}


def add_task(conn: sqlite3.Connection, text: str, *, project_id: str,
             detail: str = "", tags: list[str] | None = None,
             untrusted: bool = False) -> Task:
    _ensure_pool(conn)
    if not text or not text.strip():
        raise PoolError(Code.USAGE, "add requires non-empty text")
    created = now_iso()
    cur = conn.execute(
        f"INSERT INTO tasks ({', '.join(PUBLIC_COLUMNS)}) "
        "VALUES (:id, :project_id, :text, :detail, :status, :created_at, :claimed_at, "
        ":done_at, :archived_at, :claimed_by, :delivery_repo, :delivery_sha, "
        ":tags_json, :depends_json, :untrusted, :score_json, :estimate_hours)",
        {
            "id": None, "project_id": project_id, "text": text.strip(),
            "detail": detail, "status": TaskStatus.CANDIDATE.value,
            "created_at": created, "claimed_at": None, "done_at": None,
            "archived_at": None, "claimed_by": None, "delivery_repo": None,
            "delivery_sha": None, "tags_json": json.dumps(tags or []), "depends_json": "[]",
            "untrusted": int(untrusted), "score_json": None, "estimate_hours": None,
        },
    )
    conn.commit()
    from .events import append_event
    task = get_task(conn, cur.lastrowid)
    append_event(conn, task.id, "added", {"project_id": task.project_id,
                                          "untrusted": bool(task.untrusted)})
    conn.commit()
    return task


def get_task(conn: sqlite3.Connection, task_id: int) -> Task:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise PoolError(Code.TASK_NOT_FOUND, f"件 #{task_id} 不存在", {"id": task_id})
    return _row_to_task(row)


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"], project_id=row["project_id"], text=row["text"],
        detail=row["detail"], status=TaskStatus(row["status"]),
        created_at=row["created_at"], claimed_at=row["claimed_at"],
        done_at=row["done_at"], archived_at=row["archived_at"],
        claimed_by=row["claimed_by"], delivery_repo=row["delivery_repo"],
        delivery_sha=row["delivery_sha"], tags_json=row["tags_json"],
        depends_json=row["depends_json"], untrusted=bool(row["untrusted"]),
        score_json=row["score_json"], estimate_hours=row["estimate_hours"],
    )


def _effective_score(task: Task) -> float | None:
    """score_json 形如 {"score": <number>}；解析失败视为无评分（不阻塞 next）。"""
    if not task.score_json:
        return None
    try:
        val = json.loads(task.score_json)
    except (TypeError, ValueError):
        return None
    if isinstance(val, dict):
        val = val.get("score")
    return float(val) if isinstance(val, (int, float)) else None


def _wait_days(task: Task) -> float:
    try:
        created = datetime.fromisoformat(task.created_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 86400)


def select_reason(candidates: list[Task], chosen: Task) -> str:
    """一行选择理由（§5.2）：只引用公开字段，可解释。"""
    days = _wait_days(chosen)
    scored = [t for t in candidates if _effective_score(t) is not None]
    if scored and _effective_score(chosen) is not None:
        return f"highest score ({_effective_score(chosen):g}), waited {days:.1f} days"
    ties = [t for t in candidates if _effective_score(t) is None]
    if len(ties) > 1:
        return f"oldest unscored (waited {days:.1f} days); ties broken by lowest id"
    return f"waited {days:.1f} days"


def next_task(conn: sqlite3.Connection, *, actor: str, project_id: str | None = None,
              tags: list[str] | None = None) -> tuple[Task, str]:
    """原子认领一件。排序：有效评分 desc → created_at asc → id asc（§5.2）。

    project_id 限定单项目池视图；tags 只缩小集合不改变排序。
    已有在办件（本 actor 名下 claimed）→ TASK_ALREADY_CLAIMED（对应档 WIP 上限）。
    """
    _ensure_pool(conn)
    try:
        conn.execute("BEGIN IMMEDIATE")
        wip = conn.execute(
            "SELECT * FROM tasks WHERE status = ? AND claimed_by = ? ORDER BY id LIMIT 1",
            (TaskStatus.CLAIMED.value, actor),
        ).fetchone()
        if wip is not None:
            conn.rollback()
            t = _row_to_task(wip)
            raise PoolError(
                Code.TASK_ALREADY_CLAIMED,
                f"task #{t.id} is already in progress (run `pool done` first); not claiming twice",
                {"claimed_task_id": t.id},
            )

        sql = "SELECT * FROM tasks WHERE status = ?"
        params: list = [TaskStatus.CANDIDATE.value]
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        rows = conn.execute(sql, params).fetchall()
        tasks = [t for t in map(_row_to_task, rows)
                 if not tags or set(json.loads(t.tags_json)) & set(tags)]
        if not tasks:
            conn.rollback()
            total = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
            if total == 0:
                raise PoolError(Code.POOL_EMPTY, "pool is empty: run `pool add` first")
            raise PoolError(Code.TASK_NOT_CLAIMABLE, "no claimable candidate (filter or task status)")

        chosen = min(tasks, key=lambda t: (
            -(_effective_score(t) if _effective_score(t) is not None else float("-inf")),
            t.created_at, t.id,
        ))
        reason = select_reason(tasks, chosen)
        ts = now_iso()
        cur = conn.execute(
            "UPDATE tasks SET status = ?, claimed_at = ?, claimed_by = ? "
            "WHERE id = ? AND status = ?",
            (TaskStatus.CLAIMED.value, ts, actor, chosen.id, TaskStatus.CANDIDATE.value),
        )
        if cur.rowcount != 1:  # 并发竞态防御：状态已被改走
            conn.rollback()
            raise PoolError(Code.TASK_NOT_CLAIMABLE, f"task #{chosen.id} was just claimed by someone else")
        conn.commit()
        chosen.status = TaskStatus.CLAIMED
        chosen.claimed_at = ts
        chosen.claimed_by = actor
        from .events import append_event
        append_event(conn, chosen.id, "claimed", {"actor": actor, "reason": reason})
        conn.commit()
        return chosen, reason
    except sqlite3.OperationalError as exc:
        conn.rollback()
        if "locked" in str(exc).lower():
            raise PoolError(Code.DB_LOCKED, f"数据库被锁：{exc}") from None
        raise
