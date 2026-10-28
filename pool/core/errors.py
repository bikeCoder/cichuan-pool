"""V1 错误码与异常（design-v1 §5.3）。

agent 只依赖 code，不解析 message。退出码：
0 成功；2 调用/参数错误；3 可预期业务拒绝；4 环境/存储错误。
"""
from __future__ import annotations

import enum


class Code(str, enum.Enum):
    POOL_NOT_INITIALIZED = "POOL_NOT_INITIALIZED"
    POOL_ALREADY_INITIALIZED = "POOL_ALREADY_INITIALIZED"
    POOL_EMPTY = "POOL_EMPTY"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_NOT_CLAIMABLE = "TASK_NOT_CLAIMABLE"
    TASK_ALREADY_CLAIMED = "TASK_ALREADY_CLAIMED"
    TASK_NOT_CLAIMED_BY_ACTOR = "TASK_NOT_CLAIMED_BY_ACTOR"
    DELIVERY_SHA_INVALID = "DELIVERY_SHA_INVALID"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    DELIVERY_UNCONFIRMED = "DELIVERY_UNCONFIRMED"
    PROJECT_MISMATCH = "PROJECT_MISMATCH"
    PROJECT_UNRESOLVED = "PROJECT_UNRESOLVED"
    CONFIG_INVALID = "CONFIG_INVALID"
    DB_LOCKED = "DB_LOCKED"
    IMPORT_FORMAT_UNSUPPORTED = "IMPORT_FORMAT_UNSUPPORTED"
    IMPORT_CONFLICT = "IMPORT_CONFLICT"
    USAGE = "USAGE"  # 参数缺失/非法（设计 §5.3 初始集之外的调用面码，语义=2 档）


# 退出码分档：3 = 可预期业务拒绝；4 = 环境/存储；2 = 调用/参数
_EXIT_4 = frozenset({Code.POOL_NOT_INITIALIZED, Code.DB_LOCKED})
_EXIT_2 = frozenset({Code.USAGE, Code.CONFIG_INVALID})


class PoolError(Exception):
    def __init__(self, code: Code, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def exit_code(self) -> int:
        if self.code in _EXIT_4:
            return 4
        if self.code in _EXIT_2:
            return 2
        return 3


def exit_code_of(code: Code) -> int:
    return PoolError(code, "").exit_code
