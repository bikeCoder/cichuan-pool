"""MCP 工具注册表：四工具（+只读 pool_list）的声明与薄封装分发。

约定（路线图 D3）：CLI 是唯一逻辑真相源——写工具的 handler 一律转发到
``pool.cli.main`` 的同名命令函数，本模块不复制任何生命周期/校验规则；
错误沿 PoolError 原样上抛，由 server 层转成与 CLI ``--json`` 同构的
envelope（agent 依旧只依赖 error.code）。
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from ..core.errors import Code, PoolError

ACCESS_READ = "read"
ACCESS_WRITE = "write"

# MCP 层新增的闸码（只出现在 MCP 面，不动 CLI 错误码契约）
CODE_WRITE_DISABLED = "MCP_WRITE_DISABLED"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    access: str  # ACCESS_READ | ACCESS_WRITE
    input_schema: dict
    handler: Callable[[dict, str | None], dict]  # (arguments, data_dir) -> data


def _ns(**kw) -> SimpleNamespace:
    return SimpleNamespace(**kw)


def _cli_call(cmd_fn: Callable, data_dir: str | None, **args) -> dict:
    """转发到 CLI 命令函数：同样的解析、同样的错误码、同样的返回 data。"""
    data, _exit = cmd_fn(_ns(**args), data_dir)
    return data


def _tool_add(args: dict, data_dir: str | None) -> dict:
    return _cli_call(_import_cli().cmd_add, data_dir,
                     text=args["text"], detail=args.get("detail") or "",
                     tag=list(args.get("tags") or []),
                     untrusted=bool(args.get("untrusted", False)),
                     cwd=args.get("cwd"))


def _tool_next(args: dict, data_dir: str | None) -> dict:
    return _cli_call(_import_cli().cmd_next, data_dir,
                     tag=list(args.get("tags") or []))


def _tool_done(args: dict, data_dir: str | None) -> dict:
    return _cli_call(_import_cli().cmd_done, data_dir,
                     id=int(args["id"]), commit=args["commit"])


def _tool_sync(args: dict, data_dir: str | None) -> dict:
    return _cli_call(_import_cli().cmd_sync, data_dir,
                     repo=args.get("repo") or ".")


def _tool_list(args: dict, data_dir: str | None) -> dict:
    """只读查询（权限分离的 read 侧执行点）：与 board 同源的 SELECT 读路径。"""
    from ..store import db as store_db
    from ..store.paths import resolve_db_path

    db_path = resolve_db_path(data_dir)
    if not db_path.exists():
        raise PoolError(Code.POOL_NOT_INITIALIZED,
                        f"pool not initialized ({db_path} missing): run `pool init` first")
    try:
        conn = store_db.connect(db_path)
    except sqlite3.OperationalError as exc:
        raise PoolError(Code.DB_LOCKED, f"failed to open database: {exc}") from None
    cols = ["id", "project_id", "text", "status", "created_at", "claimed_at",
            "done_at", "archived_at", "claimed_by", "delivery_repo",
            "delivery_sha", "untrusted", "estimate_hours"]
    try:
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM tasks ORDER BY id").fetchall()
        return {"tasks": [dict(r) for r in rows]}
    finally:
        conn.close()


def _import_cli():
    # 延迟 import：与 cli/board 的既定边界一致，避免模块级环。
    # 注意 `from ..cli import main` 会被 __init__ re-export 的 main() 函数遮蔽，
    # 必须按全名取模块。
    from importlib import import_module

    return import_module("pool.cli.main")


_TASK_LIST_SCHEMA_PROPS = {
    "tags": {"type": "array", "items": {"type": "string"},
             "description": "过滤标签（缩小集合，不改变排序）"},
}


def build_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="pool_next",
            description="原子认领下一件任务（candidate → claimed，受当前预设档 WIP 上限约束）。"
                        "返回任务详情与选择理由；untrusted 任务只读不执行。",
            access=ACCESS_WRITE,  # 认领会改池状态，不是只读
            input_schema={"type": "object", "properties": _TASK_LIST_SCHEMA_PROPS},
            handler=_tool_next,
        ),
        ToolSpec(
            name="pool_add",
            description="新建一条 candidate 任务，返回件号。",
            access=ACCESS_WRITE,
            input_schema={"type": "object", "required": ["text"], "properties": {
                "text": {"type": "string", "description": "任务一句话描述"},
                "detail": {"type": "string", "description": "详情（现象/验收等八段）"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "untrusted": {"type": "boolean",
                              "description": "外部来源任务降权标记（agent 只读不执行）"},
                "cwd": {"type": "string",
                        "description": "项目目录（解析 project_id；缺省用服务进程 cwd）"},
            }},
            handler=_tool_add,
        ),
        ToolSpec(
            name="pool_done",
            description="为已认领任务登记交付声明（claimed → done_pending_merge）。"
                        "只登记声明；归档要等 pool_sync 核账确认。",
            access=ACCESS_WRITE,
            input_schema={"type": "object", "required": ["id", "commit"], "properties": {
                "id": {"type": "integer", "description": "任务件号"},
                "commit": {"type": "string",
                           "description": "交付 commit sha（7-40 位十六进制）"},
            }},
            handler=_tool_done,
        ),
        ToolSpec(
            name="pool_sync",
            description="核账：逐件验证交付 commit 是否到达交付仓默认分支，"
                        "strong 自动归档，weak/none 留待确认。",
            access=ACCESS_WRITE,  # 归档会改池状态
            input_schema={"type": "object", "properties": {
                "repo": {"type": "string", "description": "交付仓本地路径（缺省当前目录）"},
            }},
            handler=_tool_sync,
        ),
        ToolSpec(
            name="pool_list",
            description="只读列出池内全部任务的公开字段（不认领、不改状态）。",
            access=ACCESS_READ,
            input_schema={"type": "object", "properties": {}},
            handler=_tool_list,
        ),
    ]


def tool_to_mcp(spec: ToolSpec) -> dict:
    """ToolSpec → MCP tools/list 条目；readOnlyHint 与 access 声明强一致。"""
    return {
        "name": spec.name,
        "description": spec.description,
        "inputSchema": spec.input_schema,
        "annotations": {"readOnlyHint": spec.access == ACCESS_READ},
    }


def find_tool(name: str) -> ToolSpec | None:
    for spec in build_tool_specs():
        if spec.name == name:
            return spec
    return None


def call_tool(name: str, arguments: dict, *, data_dir: str | None,
              read_only: bool) -> dict:
    """分发一次 tools/call。返回 MCP tool result dict（content/isError）。

    权限分离执行点：read_only 闸拒绝一切写工具调用（含 pool_next——认领
    也是写）。PoolError 转成与 CLI ``--json`` 同构的 envelope，isError=true，
    agent 依旧只依赖 error.code 决策。
    """
    spec = find_tool(name)
    if spec is None:
        return _tool_result({"ok": False, "error": {
            "code": Code.USAGE.value, "message": f"unknown tool: {name}",
            "details": {"tool": name},
        }}, is_error=True)
    if read_only and spec.access == ACCESS_WRITE:
        envelope = {"ok": False, "error": {
            "code": CODE_WRITE_DISABLED,
            "message": f"tool '{name}' is a write tool; server is in read-only mode",
            "details": {"tool": name, "access": spec.access},
        }}
        return _tool_result(envelope, is_error=True)
    try:
        data = spec.handler(arguments or {}, data_dir)
    except PoolError as err:
        return _tool_result({"ok": False, "error": {
            "code": err.code.value, "message": err.message, "details": err.details,
        }}, is_error=True)
    return _tool_result({"ok": True, "data": data}, is_error=False)


def _tool_result(envelope: dict, *, is_error: bool) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(envelope, ensure_ascii=False)}],
        "isError": is_error,
    }
