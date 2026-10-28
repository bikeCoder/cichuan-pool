"""MCP JSON-RPC 2.0 stdio 服务循环（newline 分帧，零第三方依赖）。

- 传输：stdio only——不 import socket、不打开任何监听（tests 钉死）；
  远程传输/鉴权属阶段 D，明确不做；
- 权限分离执行点在 ``tools.call_tool`` / tools/list 过滤（见 tools 模块）。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import TextIO

from . import tools as mcp_tools

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "cichuan-pool"
SERVER_VERSION = "0.1.0.dev0"

ENV_READ_ONLY = "POOL_MCP_READ_ONLY"

# JSON-RPC / MCP 错误码
ERR_PARSE = -32700
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602


@dataclass
class ServerState:
    read_only: bool
    data_dir: str | None


def make_state(read_only: bool | None = None, data_dir: str | None = None) -> ServerState:
    """read_only 缺省从 env 读（POOL_MCP_READ_ONLY=1/on/true 视为开）。"""
    if read_only is None:
        raw = os.environ.get(ENV_READ_ONLY, "").strip().lower()
        read_only = raw in ("1", "on", "true", "yes")
    return ServerState(read_only=read_only, data_dir=data_dir)


def handle_message(state: ServerState, msg: dict) -> dict | None:
    """处理一条已解析的 JSON-RPC 消息；通知（无 id）返回 None。"""
    method = msg.get("method")
    msg_id = msg.get("id")
    is_notification = msg_id is None
    try:
        result = _dispatch(state, method, msg.get("params") or {})
    except _MethodNotFound:
        if is_notification:
            return None
        return _error(msg_id, ERR_METHOD_NOT_FOUND, f"method not found: {method}")
    except (_ParamsError, ValueError, KeyError, TypeError) as exc:
        if is_notification:
            return None
        return _error(msg_id, ERR_INVALID_PARAMS, f"invalid params: {exc}")
    if is_notification:
        return None
    return _ok(msg_id, result)


class _MethodNotFound(Exception):
    pass


class _ParamsError(Exception):
    pass


def _dispatch(state: ServerState, method: str | None, params: dict) -> dict:
    if method == "initialize":
        # 回显客户端版本，客户端未给则用本服务锚定版本
        version = params.get("protocolVersion") or PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "cichuan-pool task pool; CLI is the source of truth. "
                            "Claim with pool_next, deliver with pool_done, "
                            "verify with pool_sync.",
        }
    if method == "notifications/initialized" or method is None:
        return {}
    if method == "ping":
        return {}
    if method == "tools/list":
        specs = mcp_tools.build_tool_specs()
        if state.read_only:
            specs = [s for s in specs if s.access == mcp_tools.ACCESS_READ]
        return {"tools": [mcp_tools.tool_to_mcp(s) for s in specs]}
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise _ParamsError("params.name must be a non-empty string")
        arguments = params.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            raise _ParamsError("params.arguments must be an object")
        return mcp_tools.call_tool(name, arguments, data_dir=state.data_dir,
                                   read_only=state.read_only)
    raise _MethodNotFound(method)


def _ok(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": code, "message": message}}


def serve(state: ServerState, input_stream: TextIO, output_stream: TextIO) -> None:
    """逐行读取 JSON-RPC 请求并回写响应；EOF 或 Ctrl+C 结束。"""
    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            resp = handle_message(state, msg)
        except json.JSONDecodeError:
            resp = _error(None, ERR_PARSE, "parse error: invalid JSON")
        except Exception as exc:  # 兜底：单条消息异常不杀服务进程
            msg_id = msg.get("id") if isinstance(msg, dict) else None
            resp = _error(msg_id, -32603, f"internal error: {exc}")
        if resp is not None:
            output_stream.write(json.dumps(resp, ensure_ascii=False) + "\n")
            output_stream.flush()
