"""验收 #10856：pool board 可选启动——绑定面/只读/核心闭环不依赖看板。"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request

from pool.board.config import resolve_bind
from pool.board.server import make_server, serve_forever


def test_resolve_bind_defaults_loopback():
    # D9：缺省与回环一律不暴露；非回环地址一律视为对外暴露
    assert resolve_bind() == ("127.0.0.1", False)
    assert resolve_bind(None) == ("127.0.0.1", False)
    assert resolve_bind("localhost")[1] is False
    assert resolve_bind("127.0.0.1")[1] is False
    assert resolve_bind("::1")[1] is False
    assert resolve_bind("0.0.0.0") == ("0.0.0.0", True)
    assert resolve_bind("192.168.1.5") == ("192.168.1.5", True)


def test_board_server_binds_loopback_and_reads_core(env):
    """默认绑定 127.0.0.1；API 只读，数据来自 core/store 读路径。"""
    root, proj = env
    from pool.cli.main import main as cli_main
    import os
    os.environ["POOL_DATA_DIR"] = str(root)
    assert cli_main(["init"]) == 0
    assert cli_main(["add", "看板数据源", "--cwd", str(proj)]) == 0

    srv, exposed = make_server(root / "pool.db", port=0)  # port=0 → 内核分配
    assert exposed is False
    assert srv.server_address[0] == "127.0.0.1"
    import threading
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        host, port = srv.server_address[:2]
        base = f"http://{host}:{port}"
        with urllib.request.urlopen(f"{base}/api/summary", timeout=5) as r:
            data = json.loads(r.read())
        assert data["total"] == 1
        assert data["by_status"].get("candidate") == 1
        with urllib.request.urlopen(f"{base}/api/tasks", timeout=5) as r:
            tasks = json.loads(r.read())
        assert tasks[0]["id"] == 1 and tasks[0]["status"] == "candidate"
    finally:
        srv.shutdown()
        srv.server_close()


def test_board_readonly_no_write_endpoints(env):
    """看板面无写端点：POST 一律 501，绝不复制生命周期规则。"""
    root, _ = env
    from pool.cli.main import main as cli_main
    import os
    os.environ["POOL_DATA_DIR"] = str(root)
    assert cli_main(["init"]) == 0
    srv, _ = make_server(root / "pool.db", port=0)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        host, port = srv.server_address[:2]
        req = urllib.request.Request(f"http://{host}:{port}/api/next", data=b"{}",
                                     method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("POST must not succeed")
        except urllib.error.HTTPError as e:
            assert e.code == 501
    finally:
        srv.shutdown()
        srv.server_close()


def test_five_command_loop_runs_without_board(env, tmp_path):
    """未安装/不接触看板模块时，五命令核心闭环完整可用（子进程钉死）。"""
    root, proj = env
    script = f"""
import sys
from pool.cli.main import main
env = {{"POOL_DATA_DIR": r"{root}"}}
import os
os.environ.update(env)
assert main(["init"]) == 0
assert main(["add", "x", "--cwd", r"{proj}"]) == 0
assert main(["next"]) == 0
assert main(["done", "1", "--commit", "a" * 7]) == 0
assert main(["sync", "--repo", r"{proj}"]) in (0,)
print("BOARD_IMPORTED:", "pool.board" in sys.modules)
"""
    r = subprocess.run([sys.executable, "-c", script], capture_output=True,
                       text=True, timeout=60, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "BOARD_IMPORTED: False" in r.stdout
