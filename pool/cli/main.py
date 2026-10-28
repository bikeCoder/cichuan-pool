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
        raise PoolError(Code.POOL_NOT_INITIALIZED, f"pool not initialized ({db_path} missing): run `pool init` first")
    try:
        return store_db.connect(db_path)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            raise PoolError(Code.DB_LOCKED, f"database is locked: {exc}") from None
        raise PoolError(Code.DB_LOCKED, f"failed to open database: {exc}") from None


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
        data = {"task": _task_brief(task), "reason": reason}
        if task.untrusted:
            # D9：机器输出同样显式声明只读，agent 依赖结构化字段判断
            data["untrusted_readonly"] = True
            data["note"] = "untrusted task is read-only; human confirmation required before execution"
        return data, 0
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


def cmd_board(args, data_dir) -> tuple[dict, int]:
    """可选本地看板（D4/D9）：阻塞式常驻，自打印运行信息后 serve。

    默认只绑 127.0.0.1；--host 显式暴露时向 stderr 打印警告。
    看板只读（只走 store 读路径），不写数据根、不触碰项目仓。
    """
    from ..board import server as board_server
    from ..store.paths import resolve_db_path

    db_path = resolve_db_path(data_dir)
    if not db_path.exists():
        raise PoolError(Code.POOL_NOT_INITIALIZED,
                        f"pool not initialized ({db_path} missing): run `pool init` first")
    try:
        srv, exposed = board_server.make_server(db_path, args.host, args.port)
    except OSError as exc:
        raise PoolError(Code.CONFIG_INVALID,
                        f"failed to bind board server: {exc}") from None
    host, port = srv.server_address[:2]
    if exposed:
        # D9：显式暴露必须留下显式警告（stderr，不进 --json envelope）
        print(f"WARNING: board is bound to non-loopback address {host}; "
              "the API is unauthenticated (read-only). Ctrl+C to stop.",
              file=sys.stderr)
        sys.stderr.flush()
    print(f"Board serving http://{host}:{port} (read-only; Ctrl+C to stop)")
    sys.stdout.flush()
    try:
        board_server.serve_forever(srv)
    except KeyboardInterrupt:
        pass
    return {"host": str(host), "port": port, "stopped": True}, 0


def cmd_doctor(args, data_dir) -> tuple[dict, int]:
    """只读诊断报告（#10857）：待核账件按族分报，不归档不改状态。"""
    from ..core.doctor import doctor_report

    conn = _connect_or_fail(data_dir)
    try:
        return doctor_report(conn, probe_repo=args.repo), 0
    finally:
        conn.close()


def cmd_export(args, data_dir) -> tuple[dict, int]:
    from ..core.transfer import export_pool

    conn = _connect_or_fail(data_dir)
    try:
        return export_pool(conn, args.file), 0
    finally:
        conn.close()


def cmd_import(args, data_dir) -> tuple[dict, int]:
    from ..core.transfer import import_pool

    conn = _connect_or_fail(data_dir)
    try:
        return import_pool(conn, args.file), 0
    finally:
        conn.close()


def cmd_config(args, data_dir) -> tuple[dict, int]:
    from ..core import config as cfg

    conn = _connect_or_fail(data_dir)
    try:
        action = args.config_action
        if action == "show":
            return cfg.effective_config(conn), 0
        if action == "preset":
            cfg.set_preset(conn, args.preset)
            return {"preset": args.preset}, 0
        if action == "set":
            value: object = args.value
            if isinstance(value, str):
                if value.lower() in ("on", "true"):
                    value = True
                elif value.lower() in ("off", "false"):
                    value = False
                else:
                    try:
                        value = int(value)
                    except ValueError:
                        raise PoolError(Code.CONFIG_INVALID,
                                        f"cannot parse value '{args.value}' (use on/off or an integer)") from None
            cfg.set_override(conn, args.key, value)
            return cfg.effective_config(conn), 0
        if action == "unset":
            removed = cfg.unset_override(conn, args.key)
            data = cfg.effective_config(conn)
            data["removed"] = removed
            return data, 0
        raise PoolError(Code.USAGE, "config requires show|preset|set|unset")
    finally:
        conn.close()


def cmd_mcp(args, data_dir) -> tuple[dict, int]:
    """MCP server（阶段C-01）：CLI 的薄封装，stdio 传输，不涉网络。

    stdout 是 JSON-RPC 协议通道——本命令不在 stdout 打印任何横幅/结果，
    就绪信息走 stderr；serve 结束（EOF/Ctrl+C）后静默返回。
    """
    from ..mcp import server as mcp_server

    state = mcp_server.make_state(read_only=args.read_only, data_dir=data_dir)
    mode = "read-only" if state.read_only else "read-write"
    print(f"cichuan-pool MCP server ready ({mode}; stdio transport, no network)",
          file=sys.stderr)
    sys.stderr.flush()
    try:
        mcp_server.serve(state, sys.stdin, sys.stdout)
    except KeyboardInterrupt:
        pass
    return {"mode": mode, "stopped": True}, 0


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

    p_config = sub.add_parser("config", parents=[common], help="预设档与开关（solo/fleet/team）")
    config_sub = p_config.add_subparsers(dest="config_action", required=True)
    p_show = config_sub.add_parser("show", parents=[common], help="展开当前档完整开关清单")
    p_preset = config_sub.add_parser("preset", parents=[common], help="切换预设档（清空全部单项覆盖）")
    p_preset.add_argument("preset", help="solo | fleet | team")
    p_set = config_sub.add_parser("set", parents=[common], help="单项覆盖一个开关（on/off 或整数）")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_unset = config_sub.add_parser("unset", parents=[common], help="撤销单项覆盖，回到档默认")
    p_unset.add_argument("key")
    p_config.set_defaults(fn=cmd_config)
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

    p_board = sub.add_parser("board", parents=[common],
                             help="可选本地看板（只读；默认仅绑 127.0.0.1）")
    p_board.add_argument("--host", default=None,
                         help="绑定地址（缺省 127.0.0.1；非回环地址将打印暴露警告）")
    p_board.add_argument("--port", type=int, default=None,
                         help="监听端口（缺省 8765；0 表示内核自动分配）")
    p_board.set_defaults(fn=cmd_board)

    p_doctor = sub.add_parser("doctor", parents=[common],
                              help="只读诊断：待核账件按 strong/weak/none 分族出报告")
    p_doctor.add_argument("--repo", default=".", help="交付仓本地路径（缺省当前目录）")
    p_doctor.set_defaults(fn=cmd_doctor)

    p_mcp = sub.add_parser("mcp", parents=[common],
                           help="MCP server（stdio；四工具薄封装；--read-only 只读闸）")
    p_mcp.add_argument("--read-only", action="store_true", default=None,
                       help="只读模式：tools/list 只暴露读工具，写工具调用被拒")
    p_mcp.set_defaults(fn=cmd_mcp)

    p_export = sub.add_parser("export", parents=[common], help="导出版本化 JSONL（备份/换机）")
    p_export.add_argument("file")
    p_export.set_defaults(fn=cmd_export)

    p_import = sub.add_parser("import", parents=[common],
                              help="导入 JSONL（外部任务一律 untrusted，冲突不覆盖）")
    p_import.add_argument("file")
    p_import.set_defaults(fn=cmd_import)

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
            print(f"Pool ready: {data['data_dir']}")
        elif args.command == "add":
            print(f"#{data['id']} added ({data['status']}): {data['text']}")
        elif args.command == "next":
            t = data["task"]
            print(f"Claimed #{t['id']}: {t['text']}")
            print(f"Reason: {data['reason']}")
            if t.get("untrusted"):
                # D9：untrusted 任务对 agent 只读不执行，需人工确认
                print("WARNING: this task is untrusted (imported): read-only for agents; human confirmation required before execution")
        elif args.command == "done":
            tag = " (duplicate declaration, idempotent)" if data.get("idempotent") else ""
            print(f"#{data['id']} delivery registered, pending verification{tag}")
        elif args.command == "sync":
            for e in data["archived"]:
                print(f"archived #{e['id']}: {e['reason']}")
            # 待确认按三档分族（#10857）：strong-未归档 / weak / none
            _TIER_TITLES = {"strong": "strong but not auto-archived",
                            "weak": "weak evidence (needs confirm)",
                            "none": "no evidence (needs confirm)"}
            for tier in ("strong", "weak", "none"):
                entries = [e for e in data["unconfirmed"] if e.get("tier") == tier]
                if entries:
                    print(f"{_TIER_TITLES[tier]}:")
                    for e in entries:
                        print(f"  #{e['id']}: {e['reason']}")
            leftover = [e for e in data["unconfirmed"] if e.get("tier") not in ("strong", "weak", "none")]
            for e in leftover:
                print(f"unconfirmed #{e['id']}: {e['reason']}")
            if not data["archived"] and not data["unconfirmed"]:
                print("no pending delivery declarations")
        elif args.command == "doctor":
            print(f"pool doctor — {data['total']} tasks "
                  f"({', '.join(f'{k} {v}' for k, v in sorted(data['by_status'].items()))})")
            print(f"pending verification: {data['pending']}")
            _FAMILY_TITLES = {
                "no_sha": "no delivery sha registered",
                "cross_repo": "cross-repo delivery (possible multi-landing)",
                "strong": "strong (sync will archive)",
                "weak": "weak (needs confirm)",
                "none": "none (needs confirm)",
            }
            for family, entries in data["families"].items():
                if not entries:
                    continue
                print(f"{_FAMILY_TITLES[family]} ({len(entries)}):")
                for e in entries:
                    print(f"  #{e['id']} {e['text']}: {e['reason']}")
                    for hint in e.get("hints", []):
                        print(f"    - {hint}")
            if data["pending"] == 0:
                print("nothing pending verification")
        elif args.command == "config":
            action = args.config_action
            if action == "show":
                print(f"preset: {data['preset']}")
                for key, val in data.items():
                    if key in ("preset", "overrides"):
                        continue
                    print(f"  {key}: {'on' if val else 'off'}"
                          if isinstance(val, bool) else f"  {key}: {val}")
                if data.get("overrides"):
                    print(f"  (overrides: {', '.join(data['overrides'])})")
            elif action == "preset":
                print(f"Preset switched: {data['preset']} (overrides cleared)")
            elif action == "set":
                print(f"Override set: {args.key} (preset: {data['preset']})")
            elif action == "unset":
                if data.get("removed"):
                    print(f"Override removed: {args.key} (preset: {data['preset']})")
                else:
                    print(f"No override for {args.key} (preset: {data['preset']})")
        elif args.command == "export":
            print(f"Exported {data['tasks']} tasks / {data['events']} events -> {data['path']}")
        elif args.command == "import":
            t = data["tasks"]
            print(f"Import complete: tasks +{t['added']} / conflicts {t['conflict']}, "
                  f"events +{data['events']['added']}. External tasks are marked untrusted (read-only).")
    return 0
