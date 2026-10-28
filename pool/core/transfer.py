"""版本化 JSONL 导入导出（design-v1 §3.4 / D8）。

格式：首行 {"format":"cichuan-pool","version":1,"exported_at":"..."}；
后续行按 type ∈ {project, task, event} 区分，每行自包含。
导入规则：格式版本先校验；外部任务默认 untrusted=true；ID 冲突不覆盖；
报告给出新增/跳过/冲突计数。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .. import FORMAT_NAME, FORMAT_VERSION
from .errors import Code, PoolError
from .events import append_event, count_events
from .model import PUBLIC_COLUMNS, Task
from .tasks import _ensure_pool

_TASK_FIELDS = list(PUBLIC_COLUMNS)


def export_pool(conn: sqlite3.Connection, out_path: str | Path) -> dict:
    _ensure_pool(conn)
    header = {"format": FORMAT_NAME, "version": FORMAT_VERSION,
              "exported_at": datetime.now(timezone.utc)
              .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"}
    tasks = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    events = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    projects = sorted({r["project_id"] for r in tasks})
    counts = {"projects": 0, "tasks": 0, "events": 0}
    with Path(out_path).open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for p in projects:
            f.write(json.dumps({"type": "project", "project_id": p},
                               ensure_ascii=False) + "\n")
            counts["projects"] += 1
        for r in tasks:
            row = {"type": "task"}
            row.update({k: r[k] for k in _TASK_FIELDS})
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            counts["tasks"] += 1
        for r in events:
            f.write(json.dumps({"type": "event", "id": r["id"],
                                "task_id": r["task_id"], "kind": r["kind"],
                                "at": r["at"],
                                "payload_json": r["payload_json"]},
                               ensure_ascii=False) + "\n")
            counts["events"] += 1
    return {"path": str(out_path), **counts}


def _parse_header(line: str) -> dict:
    try:
        header = json.loads(line)
    except ValueError:
        raise PoolError(Code.IMPORT_FORMAT_UNSUPPORTED, "first line is not valid JSON") from None
    if not isinstance(header, dict) or header.get("format") != FORMAT_NAME:
        raise PoolError(Code.IMPORT_FORMAT_UNSUPPORTED,
                        f"missing or wrong format marker (expected {FORMAT_NAME})")
    if header.get("version") != FORMAT_VERSION:
        raise PoolError(
            Code.IMPORT_FORMAT_UNSUPPORTED,
            f"unsupported format version: file v{header.get('version')}, supported v{FORMAT_VERSION}",
            {"file_version": header.get("version"), "supported": FORMAT_VERSION},
        )
    return header


def import_pool(conn: sqlite3.Connection, in_path: str | Path) -> dict:
    """导入 JSONL。返回报告：tasks/events 各自的 added/skipped/conflict 计数与冲突清单。

    外部导入任务一律 untrusted=true（覆盖文件内标记，D9 fail-closed）；
    ID 冲突（池内已有同号件）不覆盖、计 conflict。
    """
    _ensure_pool(conn)
    path = Path(in_path)
    with path.open("r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not lines:
        raise PoolError(Code.IMPORT_FORMAT_UNSUPPORTED, "empty file")
    _parse_header(lines[0])

    report = {
        "projects": {"added": 0, "skipped": 0},
        "tasks": {"added": 0, "skipped": 0, "conflict": 0, "conflicts": []},
        "events": {"added": 0, "skipped": 0},
    }
    known_projects = {r["project_id"]
                      for r in conn.execute("SELECT DISTINCT project_id FROM tasks")}

    for lineno, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            report["tasks"]["skipped"] += 1  # 坏行不中断，计入跳过
            continue
        rtype = row.get("type")
        if rtype == "project":
            pid = row.get("project_id")
            if pid in known_projects:
                report["projects"]["skipped"] += 1
            else:
                known_projects.add(pid)
                report["projects"]["added"] += 1
        elif rtype == "task":
            exists = conn.execute("SELECT 1 FROM tasks WHERE id = ?",
                                  (row.get("id"),)).fetchone()
            if exists:
                report["tasks"]["conflict"] += 1
                report["tasks"]["conflicts"].append(
                    {"id": row.get("id"), "line": lineno,
                     "reason": "task id already exists in pool; not overwritten"})
                continue
            cols = {k: row.get(k) for k in _TASK_FIELDS}
            placeholders = ", ".join(f":{k}" for k in _TASK_FIELDS)
            conn.execute(
                f"INSERT INTO tasks ({', '.join(_TASK_FIELDS)}) VALUES ({placeholders})",
                cols,
            )
            # D9：外部导入一律 untrusted，不信任文件内标记
            conn.execute("UPDATE tasks SET untrusted = 1 WHERE id = ?", (row["id"],))
            report["tasks"]["added"] += 1
        elif rtype == "event":
            try:
                conn.execute(
                    "INSERT INTO events (id, task_id, kind, at, payload_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (row["id"], row["task_id"], row["kind"], row["at"],
                     row.get("payload_json", "{}")),
                )
                report["events"]["added"] += 1
            except sqlite3.IntegrityError:
                report["events"]["skipped"] += 1
        else:
            report["tasks"]["skipped"] += 1  # 未知类型行跳过并计数
    conn.commit()
    return report
