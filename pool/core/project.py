"""项目身份识别（design-v1 §3.1）：git remote 规范化身份，无 remote 用本地路径。

规范化形态：去协议、去 .git、小写的 "host/owner/repo"（与内部仓 doc_probe 身份口径一致）。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .errors import Code, PoolError

_REMOTE_PATTERNS = (
    re.compile(r"^git@(?P<host>[^:]+):(?P<path>.+?)(?:\.git)?$", re.I),
    re.compile(r"^ssh://git@(?P<host>[^/]+)/(?P<path>.+?)(?:\.git)?$", re.I),
    re.compile(r"^https?://[^/@]+@(?P<host>[^/]+)/(?P<path>.+?)(?:\.git)?$", re.I),
    re.compile(r"^https?://(?P<host>[^/]+)/(?P<path>.+?)(?:\.git)?$", re.I),
)


def normalize_remote(url: str) -> str | None:
    for pat in _REMOTE_PATTERNS:
        m = pat.match(url.strip())
        if m:
            return f"{m['host']}/{m['path']}".lower().rstrip("/")
    return None


def resolve_project(cwd: str | Path | None = None) -> str:
    """返回当前目录所属项目身份。无法定位 git 仓 → PROJECT_UNRESOLVED。"""
    root = Path(cwd) if cwd else Path.cwd()
    try:
        url = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise PoolError(Code.PROJECT_UNRESOLVED, f"cannot resolve project identity: git unavailable ({exc})") from None
    if url:
        ident = normalize_remote(url)
        if ident:
            return ident
    # 无 origin remote：用 git 仓根的本地路径身份
    top = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=10,
    )
    if top.returncode == 0 and top.stdout.strip():
        return Path(top.stdout.strip()).resolve().as_posix().lower()
    raise PoolError(
        Code.PROJECT_UNRESOLVED,
        f"{root} is not a git repo (no remote, no toplevel); cannot resolve project identity",
    )
