"""`python -m pool.mcp` 直入口：等价 `pool mcp` 子命令（stdio 传输）。"""
from __future__ import annotations

import sys

from . import server as mcp_server


def main() -> int:
    # data_dir 交给 CLI 层的 _connect_or_fail 统一解析（这里不预解析 db 路径）
    state = mcp_server.make_state()
    mode = "read-only" if state.read_only else "read-write"
    print(f"cichuan-pool MCP server ready ({mode}; stdio transport, no network)",
          file=sys.stderr)
    sys.stderr.flush()
    try:
        mcp_server.serve(state, sys.stdin, sys.stdout)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
