"""CLI 命令解析与人话/JSON 渲染（design-v1 §5）。

约定：agent 只依赖 JSON envelope 的 error.code；退出码 0/2/3/4。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict

from ..core import tasks as ops
from ..core.errors import Code, PoolError
from ..core.project import resolve_project

ENV_ACTOR = "POOL_ACTOR"
DEFAULT_ACTOR = "solo"


def _envelope_ok(data) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False)


def _envelope_err(err: PoolError) -> str:
    return json.dumps(
        {"ok": False, "error": {"code": err.code.value, "message": err.message,
                                "details": err.details}},
        ensure_ascii=False,
    )


def _task_brief(t) -> dict:
    d = asdict(t)
    d["status"] = t.status.value
    d["untrusted"] = bool(t.untrusted)
    return d


def _connect_or_fail(data_dir):
    from ..store import db as store_db
    from ..store.paths import resolve_db_path

    db_path = resolve_db_path(data_dir)
    if not db_path.exists():
        raise PoolError(Code.POOL_NOT_INITIALIZED, f"池未初始化（{db_path} 不存在）：先 pool init")
    try:
        return store_db.connect(db_path)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise PoolError(Code.DB_LOCKED, f"数据库被锁：{exc}") from None
        raise PoolError(Code.DB_LOCKED, f"数据库打开失败：{exc}") from None


def cmd_init(args, data_dir) -> tuple[dict, int]:
    data = ops.init_pool_cmd(data_dir)
    return data, 0


def cmd_add(args, data_dir) -> tuple[dict, int]:
    conn = _connect_or_fail(data_dir)
    try:
        project = resolve_project(args.cwd)
        task = ops.add_task(conn, args.text, project_id=project,
                            detail=args.detail or "", tags=args.tag,
                            untrusted=args.untrusted)
        return {"id": task.id, "project_id": task.project_id,
                "status": task.status.value, "text": task.text}, 0
    finally:
        conn.close()


def cmd_next(args, data_dir) -> tuple[dict, int]:
    conn = _connect_or_fail(data_dir)
    try:
        actor = os.environ.get(ENV_ACTOR, DEFAULT_ACTOR)
        task, reason = ops.next_task(conn, actor=actor, tags=args.tag)
        return {"task": _task_brief(task), "reason": reason}, 0
    finally:
        conn.close()


def cmd_done(args, data_dir) -> tuple[dict, int]:
    from ..core.delivery import done_task

    conn = _connect_or_fail(data_dir)
    try:
        actor = os.environ.get(ENV_ACTOR, DEFAULT_ACTOR)
        result = done_task(conn, args.id, args.commit, actor=actor)
        return result, 0
    finally:
        conn.close()


def cmd_sync(args, data_dir) -> tuple[dict, int]:
    from ..core.delivery import sync_pool

    conn = _connect_or_fail(data_dir)
    try:
        result = sync_pool(conn, probe_repo=args.repo)
        return result, 0  # 有待确认不是命令失败（§5.3）
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pool", description="cichuan-pool — agent-first 任务池")

    # 全局参数同时挂顶层与各子命令（agent 习惯 `pool next --json` 后置写法）。
    # 两处都 default=SUPPRESS：未出现时不写 namespace，避免子解析器覆盖顶层已解析值。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="输出稳定 JSON envelope")
    common.add_argument("--data-dir", default=argparse.SUPPRESS,
                        help="数据根目录（缺省 ~/.cichuan-pool）")
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", parents=[common], help="建池并打印数据根")
    p_init.set_defaults(fn=cmd_init)

    p_add = sub.add_parser("add", parents=[common], help="新建 candidate，返回件号")
    p_add.add_argument("text")
    p_add.add_argument("--detail", default="")
    p_add.add_argument("--tag", action="append", default=[])
    p_add.add_argument("--untrusted", action="store_true", help="外部导入任务降权标记")
    p_add.add_argument("--cwd", default=None, help=argparse.SUPPRESS)  # 测试注入项目目录
    p_add.set_defaults(fn=cmd_add)

    p_next = sub.add_parser("next", parents=[common], help="原子认领一件，返回任务与选择理由")
    p_next.add_argument("--tag", action="append", default=[])
    p_next.set_defaults(fn=cmd_next)

    p_done = sub.add_parser("done", parents=[common], help="登记交付声明，进入待核账")
    p_done.add_argument("id", type=int)
    p_done.add_argument("--commit", required=True, help="交付 commit sha（7-40 位十六进制）")
    p_done.set_defaults(fn=cmd_done)

    p_sync = sub.add_parser("sync", parents=[common], help="核账：strong 自动归档，weak/none 待确认")
    p_sync.add_argument("--repo", default=".", help="交付仓本地路径（缺省当前目录）")
    p_sync.set_defaults(fn=cmd_sync)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    json_flag = getattr(args, "json", False)
    data_dir = getattr(args, "data_dir", None)
    try:
        data, _ = args.fn(args, data_dir)
    except PoolError as err:
        if json_flag:
            print(_envelope_err(err))
        else:
            print(f"pool: {err.message} [{err.code.value}]", file=sys.stderr)
        return err.exit_code
    except BrokenPipeError:
        return 0
    if json_flag:
        print(_envelope_ok(data))
    else:
        if args.command == "init":
            print(f"池已就绪：{data['data_dir']}")
        elif args.command == "add":
            print(f"#{data['id']} 已入池（{data['status']}）：{data['text']}")
        elif args.command == "next":
            t = data["task"]
            print(f"认领 #{t['id']}：{t['text']}")
            print(f"理由：{data['reason']}")
        elif args.command == "done":
            tag = "（重复声明，幂等）" if data.get("idempotent") else ""
            print(f"#{data['id']} 已登记交付，待核账{tag}")
        elif args.command == "sync":
            for e in data["archived"]:
                print(f"✓ 归档 #{e['id']}：{e['reason']}")
            for e in data["unconfirmed"]:
                print(f"· 待确认 #{e['id']}：{e['reason']}")
            if not data["archived"] and not data["unconfirmed"]:
                print("没有待核账的交付声明")
    return 0
