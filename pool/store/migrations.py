"""schema 迁移注册表：v(n) → v(n+1) 的逐步迁移。

纪律：迁移只追加不改写；每步必须幂等失败安全（失败即整体回滚到备份）。
V1 起步库直接由 create_schema 建到 SCHEMA_VERSION，这里预留演化通道。
"""
from __future__ import annotations

import sqlite3
from typing import Callable

Step = Callable[[sqlite3.Connection], None]

_STEPS: dict[int, Step] = {}


def get_step(version: int) -> Step | None:
    """返回把 v`version` 迁到 v`version+1` 的步骤。"""
    return _STEPS.get(version)


def register(from_version: int) -> Callable[[Step], Step]:
    def deco(fn: Step) -> Step:
        _STEPS[from_version] = fn
        return fn
    return deco
