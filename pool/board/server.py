"""可选本地看板服务（D4 可选伴侣 / D9 安全基线）。

- 绑定缺省唯一来源是 ``pool.board.config``：默认只绑 127.0.0.1，
  ``--host`` 显式暴露由 CLI 面打印警告（本模块不做二次判断）；
- 只读：只调用 core/store 的读路径（SELECT），不复制生命周期规则、
  不写数据根、不触碰项目仓——与 CLI 写路径完全隔离；
- 零第三方依赖（stdlib http.server）：「未安装看板依赖」在 V1 不存在，
  核心闭环与 board 互不 import（tests 钉死）。
"""
from __future__ import annotations

import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import DEFAULT_HOST, DEFAULT_PORT, resolve_bind

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "resolve_bind", "make_server", "serve_forever"]

_INDEX_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>cichuan-pool board</title></head>
<body>
<h1>cichuan-pool board</h1>
<p>Local, read-only companion API. Endpoints:</p>
<ul>
  <li><code>GET /api/summary</code> — task counts by status</li>
  <li><code>GET /api/tasks</code> — task list (public fields only)</li>
</ul>
<p>This server is read-only; lifecycle changes go through the <code>pool</code> CLI.</p>
</body></html>
"""


def _summary(conn: sqlite3.Connection) -> dict:
    by_status = {
        row["status"]: row["n"]
        for row in conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status")
    }
    total = conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
    return {"total": total, "by_status": by_status}


def _tasks(conn: sqlite3.Connection) -> list[dict]:
    cols = ["id", "project_id", "text", "status", "created_at", "claimed_at",
            "done_at", "archived_at", "claimed_by", "delivery_repo",
            "delivery_sha", "untrusted", "estimate_hours"]
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM tasks ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def make_handler(db_path: Path) -> type[BaseHTTPRequestHandler]:
    class BoardHandler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                body = _INDEX_PAGE.encode("utf-8")
                self._send(200, body, "text/html; charset=utf-8")
                return
            if path in ("/api/summary", "/api/tasks"):
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                try:
                    data = _summary(conn) if path == "/api/summary" else _tasks(conn)
                finally:
                    conn.close()
                self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
                return
            self._send(404, b'{"error":"not found"}', "application/json")

        def log_message(self, fmt, *args):  # 静默访问日志，看板是常驻本地服务
            pass

    return BoardHandler


def make_server(db_path: Path, host: str | None = None,
                port: int | None = None) -> tuple[ThreadingHTTPServer, bool]:
    """建服务（不阻塞）。返回 (server, exposed)；绑定地址缺省 127.0.0.1。"""
    bind_host, exposed = resolve_bind(host)
    handler = make_handler(Path(db_path))
    server = ThreadingHTTPServer((bind_host, port or DEFAULT_PORT), handler)
    return server, exposed


def serve_forever(server: ThreadingHTTPServer) -> None:
    try:
        server.serve_forever()
    finally:
        server.server_close()
