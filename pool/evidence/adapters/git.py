"""git 兜底适配器（design-v1 §4.3）。

算法：
1. sha 缺失 / repo 不可读 / 对象不存在 → none；
2. sha 是默认分支祖先 → strong, delivered=true；
3. sha 存在但只在非默认 ref → weak；
4. 探测所用 repo 与任务项目身份不符 → project_mismatch=true，禁止自动归档；
5. 不 fetch、不改 ref、不写工作区——对项目仓只读。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..base import Evidence, Tier
from ...core.project import normalize_remote


def _git(repo: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=30)
    return r.returncode, (r.stdout or "").strip()


def default_branch(repo: Path) -> str | None:
    rc, ref = _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD")
    if rc == 0 and ref:
        return ref.rsplit("/", 1)[-1]
    for cand in ("main", "master"):
        rc, _ = _git(repo, "show-ref", "--verify", f"refs/heads/{cand}")
        if rc == 0:
            return cand
    rc, cur = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return cur if rc == 0 and cur and cur != "HEAD" else None


def repo_identity(repo: Path) -> str | None:
    rc, url = _git(repo, "remote", "get-url", "origin")
    if rc == 0 and url:
        ident = normalize_remote(url)
        if ident:
            return ident
    rc, top = _git(repo, "rev-parse", "--show-toplevel")
    if rc == 0 and top:
        return Path(top).resolve().as_posix().lower()
    return None


def probe(repo: str | Path, sha: str | None, *, project_id: str) -> Evidence:
    repo_path = Path(repo)
    details = {"repo": str(repo_path), "sha": sha, "project_id": project_id}

    identity = repo_identity(repo_path)
    details["probe_identity"] = identity
    mismatch = identity is None or identity != project_id.lower()
    details["project_mismatch"] = mismatch

    if not sha:
        return Evidence(Tier.NONE, "no delivery sha (run `pool done --commit <sha>`)", details=details)
    if not repo_path.is_dir() or identity is None:
        return Evidence(Tier.NONE, f"delivery repo unreadable or not a git repo: {repo_path}", details=details)
    if mismatch:
        return Evidence(
            Tier.NONE,
            f"project mismatch: task belongs to {project_id}, probe repo is {identity}; will not auto-archive",
            project_mismatch=True,
            details=details,
        )

    rc, _ = _git(repo_path, "cat-file", "-e", f"{sha}^{{commit}}")
    if rc != 0:
        return Evidence(Tier.NONE, f"object missing or unreachable: {sha[:12]}", details=details)

    branch = default_branch(repo_path)
    details["default_branch"] = branch
    if branch:
        rc, _ = _git(repo_path, "merge-base", "--is-ancestor", sha, branch)
        if rc == 0:
            details["refs"] = [branch]
            return Evidence(
                Tier.STRONG, f"commit {sha[:12]} is on default branch {branch}",
                delivered=True, details=details,
            )

    rc, branches = _git(repo_path, "branch", "--contains", sha)
    refs = [b.lstrip("* ").strip() for b in branches.splitlines() if b.strip()]
    details["refs"] = refs
    if refs:
        return Evidence(
            Tier.WEAK, f"commit {sha[:12]} only on non-default branch(es) {','.join(refs)}; not merged",
            details=details,
        )
    # 无分支包含（游离/悬挂提交）：属「漏报 strong 为 weak 允许」档——记 none 并说明
    return Evidence(Tier.NONE, f"commit {sha[:12]} is on no branch (dangling commit)", details=details)
