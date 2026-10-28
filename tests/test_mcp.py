"""验收 #10859：MCP server 四工具 + 读写权限分离 + stdio 传输实测。

- 薄封装约定：写工具错误码与 CLI 完全一致（转发 cli.main 命令函数）；
- 权限分离：pool_next/pool_add/pool_done/pool_sync 均为写（认领/归档也改池
  状态），pool_list 是只读读路径；--read-only / POOL_MCP_READ_ONLY 闸生效；
- 传输：stdio only——pool/mcp 不 import socket，不涉网络（远程属阶段 D）。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

from pool.cli.main import main as cli_main
from pool.mcp import server as mcp_server
from pool.mcp import tools as mcp_tools

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TOOLS = ["pool_next", "pool_add", "pool_done", "pool_sync"]


def _rpc(method, params=None, msg_id=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    if msg_id is not None:
        msg["id"] = msg_id
    return msg


def _result_text(resp: dict) -> dict:
    """tools/call 结果里的 envelope（agent 只依赖 error.code 的同构体）。"""
    return json.loads(resp["result"]["content"][0]["text"])


# ---------- 注册表与权限声明 ----------

def test_registry_has_four_required_tools_all_write():
    specs = {s.name: s for s in mcp_tools.build_tool_specs()}
    for name in REQUIRED_TOOLS:
        assert name in specs, f"missing required tool {name}"
        assert specs[name].access == mcp_tools.ACCESS_WRITE, name
    assert specs["pool_list"].access == mcp_tools.ACCESS_READ


def test_annotations_match_access_declaration():
    # readOnlyHint 是宿主自动放行只读工具的依据，必须与 access 声明强一致
    for spec in mcp_tools.build_tool_specs():
        entry = mcp_tools.tool_to_mcp(spec)
        assert entry["annotations"]["readOnlyHint"] == (spec.access == mcp_tools.ACCESS_READ)
        assert entry["inputSchema"].get("type") == "object"


# ---------- 权限分离闸 ----------

def test_read_only_mode_filters_tools_and_rejects_writes(env):
    root, proj = env
    assert cli_main(["init"]) == 0

    state = mcp_server.make_state(read_only=True)

    # tools/list 只剩只读工具
    resp = mcp_server.handle_message(state, _rpc("tools/list", msg_id=1))
    names = [t["name"] for t in resp["result"]["tools"]]
    assert names == ["pool_list"]

    # 写调用被闸拒绝（MCP 层码，不动 CLI 错误码契约）
    resp = mcp_server.handle_message(state, _rpc(
        "tools/call", {"name": "pool_add", "arguments": {"text": "x"}}, msg_id=2))
    env_err = _result_text(resp)
    assert resp["result"]["isError"] is True
    assert env_err["error"]["code"] == mcp_tools.CODE_WRITE_DISABLED

    # 只读工具照常工作
    resp = mcp_server.handle_message(state, _rpc(
        "tools/call", {"name": "pool_list", "arguments": {}}, msg_id=3))
    assert resp["result"]["isError"] is False
    assert _result_text(resp)["data"]["tasks"] == []


def test_read_only_env_default(monkeypatch):
    monkeypatch.setenv(mcp_server.ENV_READ_ONLY, "1")
    assert mcp_server.make_state().read_only is True
    monkeypatch.delenv(mcp_server.ENV_READ_ONLY)
    assert mcp_server.make_state().read_only is False


# ---------- 协议面 ----------

def test_initialize_and_unknown_method():
    state = mcp_server.make_state(read_only=False)
    resp = mcp_server.handle_message(
        state, _rpc("initialize", {"protocolVersion": "2025-06-18",
                                   "capabilities": {}, "clientInfo": {}}, msg_id=1))
    assert resp["result"]["protocolVersion"] == "2025-06-18"
    assert resp["result"]["serverInfo"]["name"] == "cichuan-pool"
    # 通知不回包
    assert mcp_server.handle_message(
        state, _rpc("notifications/initialized")) is None
    # 未知方法 → -32601
    resp = mcp_server.handle_message(state, _rpc("no/such", msg_id=2))
    assert resp["error"]["code"] == -32601


def test_stdio_loop_parse_error_and_framing():
    state = mcp_server.make_state(read_only=True)
    inp = io.StringIO("not-json\n\n" + json.dumps(_rpc("ping", msg_id=7)) + "\n")
    out = io.StringIO()
    mcp_server.serve(state, inp, out)
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["result"] == {}


def test_unknown_tool_reports_cli_usage_code(env):
    root, _ = env
    assert cli_main(["init"]) == 0
    state = mcp_server.make_state(read_only=False)
    resp = mcp_server.handle_message(state, _rpc(
        "tools/call", {"name": "pool_nothing", "arguments": {}}, msg_id=1))
    assert _result_text(resp)["error"]["code"] == "USAGE"


# ---------- stdio 传输端到端（子进程实测四工具闭环） ----------

def test_stdio_end_to_end_four_tools(env):
    root, proj = env
    assert cli_main(["init"]) == 0

    child_env = os.environ.copy()
    child_env.update({
        "POOL_DATA_DIR": str(root),
        "POOL_ACTOR": "mcp-agent",
        "PYTHONPATH": str(REPO_ROOT),
    })
    proc = subprocess.Popen(
        [sys.executable, "-m", "pool.mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=child_env, cwd=str(REPO_ROOT), text=True, encoding="utf-8")

    def ask(msg):
        proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    try:
        # 握手
        resp = ask(_rpc("initialize", {"protocolVersion": "2025-06-18",
                                       "capabilities": {}, "clientInfo": {"name": "t"}},
                       msg_id=1))
        assert resp["result"]["serverInfo"]["name"] == "cichuan-pool"
        proc.stdin.write(json.dumps(_rpc("notifications/initialized")) + "\n")
        proc.stdin.flush()

        resp = ask(_rpc("tools/list", msg_id=2))
        names = {t["name"] for t in resp["result"]["tools"]}
        assert set(REQUIRED_TOOLS) <= names

        # add → next → done → sync 全链
        resp = ask(_rpc("tools/call", {"name": "pool_add",
                                       "arguments": {"text": "mcp e2e 件",
                                                     "cwd": str(proj)}}, msg_id=3))
        added = _result_text(resp)
        assert added["ok"] is True, f"pool_add failed: {added}"
        assert added["data"]["status"] == "candidate"

        resp = ask(_rpc("tools/call", {"name": "pool_next",
                                       "arguments": {}}, msg_id=4))
        claimed = _result_text(resp)
        assert claimed["ok"] is True and claimed["data"]["task"]["status"] == "claimed"

        resp = ask(_rpc("tools/call", {"name": "pool_done",
                                       "arguments": {"id": claimed["data"]["task"]["id"],
                                                     "commit": "deadbee1"}}, msg_id=5))
        done = _result_text(resp)
        assert done["ok"] is True and done["data"]["status"] == "done_pending_merge"

        resp = ask(_rpc("tools/call", {"name": "pool_sync",
                                       "arguments": {"repo": str(proj)}}, msg_id=6))
        synced = _result_text(resp)
        # 伪造 sha 到不了默认分支 → 不归档但命令成功，返回结构化待确认
        assert synced["ok"] is True and "unconfirmed" in synced["data"]

        resp = ask(_rpc("tools/call", {"name": "pool_list",
                                       "arguments": {}}, msg_id=7))
        listed = _result_text(resp)
        assert listed["ok"] is True and len(listed["data"]["tasks"]) == 1

        # 写工具错误码与 CLI 一致：空池 next 的下一件应报 TASK_NOT_CLAIMABLE
        resp = ask(_rpc("tools/call", {"name": "pool_next",
                                       "arguments": {}}, msg_id=8))
        assert _result_text(resp)["error"]["code"] == "TASK_NOT_CLAIMABLE"
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


# ---------- 传输边界：不涉网络 ----------

def test_mcp_package_never_touches_network():
    # D9：本阶段只做 stdio 传输——AST 级检查不允许 import socket/http 服务
    # 原语，防止「顺手」开监听绕过 127.0.0.1 基线（远程传输/鉴权属阶段 D）。
    import ast

    banned_roots = {"socket", "http", "urllib", "asyncio", "socketserver"}
    for py in (REPO_ROOT / "pool" / "mcp").glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] not in banned_roots for a in node.names), py.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned_roots, py.name
