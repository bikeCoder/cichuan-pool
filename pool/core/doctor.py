"""doctor 诊断分层报告（#10857，design-v1 §5.1 扩展）。

只读诊断：对全部 done_pending_merge 逐件取证分族，不做任何归档/写库——
归档仍只属于 sync。每件落入且仅落入一个族（互斥，按优先级判定）：

1. ``no_sha``     待核账但缺交付 sha（存量/异常件）；
2. ``cross_repo`` 探测仓与任务项目身份不符（疑似多落点交付）；
3. ``strong``     已在默认分支（sync 会自动归档）；
4. ``weak``       存在但未合并——附「借代理核验 / 人工确认」两个动作提示；
5. ``none``       其余（对象缺失、仓不可读等）。
"""
from __future__ import annotations

import sqlite3

from .tasks import _ensure_pool

WEAK_HINTS = [
    ("borrow an agent to verify",
     "have an agent merge the branch or re-check the commit, then re-run `pool sync --repo <repo>`"),
    ("human confirm",
     "inspect refs yourself (`git branch --contains <sha>`); weak evidence is never auto-archived"),
]

FAMILY_ORDER = ("no_sha", "cross_repo", "strong", "weak", "none")


def _family_of(entry: dict) -> str:
    if entry.get("project_mismatch"):
        return "cross_repo"
    tier = entry.get("tier", "none")
    return tier if tier in ("strong", "weak", "none") else "none"


def doctor_report(conn: sqlite3.Connection, *, probe_repo: str,
                  evidence_probe=None) -> dict:
    """全池诊断：状态计数 + 待核账件五族分报，全部只读。"""
    _ensure_pool(conn)
    if evidence_probe is None:
        from ..evidence.adapters.git import probe as evidence_probe

    by_status: dict[str, int] = {}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"):
        by_status[row["status"]] = row["n"]

    families: dict[str, list[dict]] = {f: [] for f in FAMILY_ORDER}
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status = 'done_pending_merge' ORDER BY id"
    ).fetchall()
    for row in rows:
        base = {"id": row["id"], "text": row["text"],
                "delivery_sha": row["delivery_sha"]}
        if not row["delivery_sha"]:
            families["no_sha"].append({
                **base, "reason": "pending verification but no delivery sha registered",
            })
            continue
        try:
            ev = evidence_probe(probe_repo, row["delivery_sha"],
                                project_id=row["project_id"])
        except Exception as exc:  # 逐件降级，与 sync 同策略
            families["none"].append({**base, "reason": f"probe error: {exc}"})
            continue
        d = ev.to_dict()
        entry = {**base, "reason": d["reason"]}
        if d["tier"] == "weak":
            entry["hints"] = [f"{label}: {hint}" for label, hint in WEAK_HINTS]
        family = "cross_repo" if d["project_mismatch"] else d["tier"]
        families[family].append(entry)

    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "pending": len(rows),
        "families": {f: families[f] for f in FAMILY_ORDER},
    }
