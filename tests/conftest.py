"""共享夹具：临时数据根 / 临时 git 项目。"""
from __future__ import annotations

import subprocess

import pytest


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / "poolroot"
    d.mkdir()
    return d


@pytest.fixture
def env(monkeypatch, tmp_path):
    """池数据根 + 带 origin remote 的临时项目仓。"""
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("POOL_DATA_DIR", str(root))
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    subprocess.run(["git", "-C", str(proj), "remote", "add", "origin",
                    "https://github.com/me/demo.git"], check=True)
    return root, proj
