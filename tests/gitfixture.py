"""临时仓对抗测试夹具（design-v1 §4.4）：不访问 hub、网络或用户真实仓库。"""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(repo: Path, *args: str, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=30)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败：{r.stderr}")
    return r


def make_repo(path: Path, *, remote_url: str | None = "https://github.com/me/demo.git") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main", ".")
    if remote_url:
        _git(path, "remote", "add", "origin", remote_url)
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    (path / "a.txt").write_text("1", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "base")
    return path


def commit(path: Path, msg: str, file: str = "a.txt", content: str = "x") -> str:
    (path / file).write_text(content, encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", msg)
    return _git(path, "rev-parse", "HEAD").stdout.strip()


def feature_branch_commit(path: Path, branch: str = "feature") -> str:
    _git(path, "checkout", "-q", "-b", branch)
    sha = commit(path, "feature work", file="f.txt")
    _git(path, "checkout", "-q", "main")
    return sha


def dangling_commit(path: Path) -> str:
    """创建一个不在任何分支上的游离提交。"""
    _git(path, "checkout", "-q", "--detach")
    sha = commit(path, "dangling", file="d.txt")
    _git(path, "checkout", "-q", "main")
    return sha
