"""数据根覆盖与入口冒烟（design-v1 §3.1 / pyproject scripts）。"""
from __future__ import annotations

from pool.cli import main
from pool.store.paths import ENV_DATA_DIR, default_data_dir, resolve_db_path


def test_env_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "custom"))
    assert default_data_dir() == tmp_path / "custom"
    assert resolve_db_path().parent == tmp_path / "custom"


def test_explicit_data_dir_beats_env(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "from-env"))
    assert resolve_db_path(tmp_path / "explicit").parent == tmp_path / "explicit"


def test_cli_placeholder_entry():
    # 阶段 A-03 接线前：入口存在、明确报未实现，不静默成功
    assert main([]) == 2
