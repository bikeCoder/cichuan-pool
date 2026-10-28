"""board 本地服务安全基线（D9）：默认只绑 127.0.0.1。

--host 显式暴露必须经调用方显式告警；本常量是唯一缺省来源。
看板服务本体在阶段 A 后期落地，先钉死绑定边界。
"""
from __future__ import annotations

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def resolve_bind(host: str | None = None) -> tuple[str, bool]:
    """返回 (绑定地址, 是否对外暴露)。非回环地址一律视为对外暴露。"""
    h = host or DEFAULT_HOST
    exposed = h not in ("127.0.0.1", "localhost", "::1")
    return h, exposed
