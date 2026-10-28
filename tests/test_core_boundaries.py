"""验收：core 不依赖 hub；状态机与契约一致；公开模型不含内部字段。"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pool.core import model
from pool.core.model import FORBIDDEN_COLUMNS, PUBLIC_COLUMNS, Task, TaskStatus, TRANSITIONS, can_transition

POOL_SRC = Path(__file__).resolve().parent.parent / "pool"


def test_core_package_does_not_import_hub():
    """core/ 全模块源码级扫描：不得出现 hub/内部仓引用。"""
    bad = ("novel_platform", "novelplatform", "cichuan_backlog", "CICHUAN_RUNS_DIR", "land_tickets")
    for py in (POOL_SRC / "core").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for n in names:
                for b in bad:
                    assert b not in n, f"{py.name} import 了内部概念：{n}"


def test_state_machine_matches_design():
    t = TaskStatus
    # design-v1 §3.3 主链
    assert can_transition(t.CANDIDATE, t.CLAIMED)
    assert can_transition(t.CLAIMED, t.DONE_PENDING_MERGE)
    assert can_transition(t.DONE_PENDING_MERGE, t.DONE)
    # 回退与 park
    assert can_transition(t.CLAIMED, t.CANDIDATE)
    assert can_transition(t.CANDIDATE, t.PARKED)
    assert can_transition(t.PARKED, t.CANDIDATE)
    # 非法边
    assert not can_transition(t.DONE, t.CLAIMED)
    assert not can_transition(t.CANDIDATE, t.DONE)
    assert not can_transition(t.DONE_PENDING_MERGE, t.CLAIMED)
    # 终态无出边
    assert TRANSITIONS[t.DONE] == frozenset()
    assert TRANSITIONS[t.SUPERSEDED] == frozenset()
    # 任意非终态 → superseded
    for s in (t.CANDIDATE, t.CLAIMED, t.DONE_PENDING_MERGE, t.PARKED):
        assert can_transition(s, t.SUPERSEDED), f"{s} 应可被取代"


def test_task_model_has_no_internal_fields():
    fields = {f for f in PUBLIC_COLUMNS}
    assert not (fields & FORBIDDEN_COLUMNS)
    # dataclass 字段与白名单一致（模型不得静默发明字段）
    dc_fields = {f.name for f in Task.__dataclass_fields__.values()}
    assert dc_fields == set(PUBLIC_COLUMNS)


def test_unregistered_migration_version_returns_none():
    from pool.store import migrations as m
    assert m.get_step(9000) is None
