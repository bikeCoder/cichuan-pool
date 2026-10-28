"""公开域模型：V1 任务字段与核心状态机（design-v1 §3.2/§3.3）。

本模块是公开 schema 的唯一真相源：任何字段进出此文件都必须先改
`docs/product/design-v1.md` 并记录契约版本。内部机制字段（launch_tier、
claim_policy、run 票据等）不得进入。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Optional


class TaskStatus(str, enum.Enum):
    CANDIDATE = "candidate"
    CLAIMED = "claimed"
    DONE_PENDING_MERGE = "done_pending_merge"
    DONE = "done"
    PARKED = "parked"
    SUPERSEDED = "superseded"


# design-v1 §3.3 状态机（邻接表）。任何迁移都必须在此表内。
TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CANDIDATE: frozenset({TaskStatus.CLAIMED, TaskStatus.PARKED, TaskStatus.SUPERSEDED}),
    TaskStatus.CLAIMED: frozenset({TaskStatus.DONE_PENDING_MERGE, TaskStatus.CANDIDATE, TaskStatus.PARKED, TaskStatus.SUPERSEDED}),
    TaskStatus.DONE_PENDING_MERGE: frozenset({TaskStatus.DONE, TaskStatus.SUPERSEDED}),
    # done / superseded 为终态；parked 只能回 candidate
    TaskStatus.PARKED: frozenset({TaskStatus.CANDIDATE, TaskStatus.SUPERSEDED}),
    TaskStatus.DONE: frozenset(),
    TaskStatus.SUPERSEDED: frozenset(),
}


def can_transition(src: TaskStatus, dst: TaskStatus) -> bool:
    return dst in TRANSITIONS.get(src, frozenset())


# design-v1 §3.2 公开字段白名单（列名 → 建表类型）。注意顺序即迁移文档顺序。
PUBLIC_COLUMNS: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY",
    "project_id": "TEXT NOT NULL",
    "text": "TEXT NOT NULL",
    "detail": "TEXT NOT NULL DEFAULT ''",
    "status": "TEXT NOT NULL DEFAULT 'candidate'",
    "created_at": "TEXT NOT NULL",
    "claimed_at": "TEXT",
    "done_at": "TEXT",
    "archived_at": "TEXT",
    "claimed_by": "TEXT",
    "delivery_repo": "TEXT",
    "delivery_sha": "TEXT",
    "tags_json": "TEXT NOT NULL DEFAULT '[]'",
    "depends_json": "TEXT NOT NULL DEFAULT '[]'",
    "untrusted": "INTEGER NOT NULL DEFAULT 0",
    "score_json": "TEXT",
    "estimate_hours": "REAL",
}

# 明确排除的内部字段——测试据此钉死「不回潮」。
FORBIDDEN_COLUMNS = frozenset({
    "launch_tier", "claim_policy", "park_reason", "wake_condition",
    "owner_run", "wip_note", "fix_class", "decision_status", "verdict",
    "anchor_file", "anchor_line", "goal_id", "parent_id",
})


@dataclass
class Task:
    """V1 公开任务（design-v1 §3.2）。字段名与 PUBLIC_COLUMNS 一一对应。"""
    id: int
    project_id: str
    text: str
    detail: str = ""
    status: TaskStatus = TaskStatus.CANDIDATE
    created_at: str = ""
    claimed_at: Optional[str] = None
    done_at: Optional[str] = None
    archived_at: Optional[str] = None
    claimed_by: Optional[str] = None
    delivery_repo: Optional[str] = None
    delivery_sha: Optional[str] = None
    tags_json: str = "[]"
    depends_json: str = "[]"
    untrusted: bool = False
    score_json: Optional[str] = None
    estimate_hours: Optional[float] = None

    def to_row(self) -> dict[str, Any]:
        row = {k: getattr(self, k) for k in PUBLIC_COLUMNS if k != "id"}
        row["id"] = self.id
        row["status"] = self.status.value
        row["untrusted"] = int(self.untrusted)
        return row
