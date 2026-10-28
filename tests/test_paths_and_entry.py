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


def test_cli_requires_subcommand():
    # 阶段 A-03 已接线：无子命令 = 参数错误（argparse 退出码 2）
    import pytest
    from pool.cli import main
    with pytest.raises(SystemExit) as ei:
        main([])
    assert ei.value.code == 2


# ---------- 进阶路径入口（#10855 阶段B-02）：help 面只显核心层 + 四路径 ----------

_CORE_COMMANDS = ("init", "add", "next", "done", "sync")
_ADVANCED_COMMANDS = ("config", "board", "doctor", "mcp", "export", "import")


def _help_text(argv):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            main(argv)
        except SystemExit as e:  # argparse --help 退出 0
            assert e.code == 0
    return buf.getvalue()


def test_top_level_help_shows_core_only_and_four_path_entries():
    text = _help_text(["--help"])
    for cmd in _CORE_COMMANDS:
        assert cmd in text
    for cmd in _ADVANCED_COMMANDS:
        assert cmd not in text
    for path in ("concurrency.md", "scale.md", "auditing.md", "governance.md"):
        assert f"docs/advanced/{path}" in text


def test_advanced_command_help_direct():
    # 显式点名进阶命令：注册并照常给 help（不列核心清单）
    text = _help_text(["doctor", "--help"])
    assert "--repo" in text


def test_advanced_command_executable_flag_first(monkeypatch, tmp_path, capsys):
    # 全局旗标前置形态（--json config show）也必须触发进阶命令注册
    import json as _json
    monkeypatch.setenv("POOL_DATA_DIR", str(tmp_path / "d"))
    assert main(["--json", "init"]) == 0
    assert main(["--json", "config", "show"]) == 0
    out = _json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is True
    assert out["data"]["preset"] == "solo"
