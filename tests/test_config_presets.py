"""验收 #10854：预设档 solo/fleet/team 与 config show。

三条硬验收（detail 原文）：
1. 三档切换行为有回归测试（行为面 = WIP 闸上限随档变化）；
2. config show 与实际行为一致（show 渲染的就是 next 读的同一份 effective_config）；
3. 缺配置 = 全关（meta 无 preset/覆盖行时回落 solo，机制全 off）。
"""
from __future__ import annotations

import contextlib
import io
import json
import sqlite3

import pytest

from pool.cli.main import main as cli_main
from pool.core import config as cfg
from pool.core import tasks as ops
from pool.core.errors import Code, PoolError
from pool.store import db as store_db


def _run_json(*argv, expect=0):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli_main([*argv])
    assert rc == expect, f"exit {rc} != {expect} for {argv}"
    return rc, json.loads(buf.getvalue().strip().splitlines()[-1])


@pytest.fixture
def pool(env):
    root, proj = env
    cli_main(["--json", "init"])
    for text in ("甲", "乙", "丙", "丁"):
        cli_main(["--json", "add", text, "--cwd", str(proj)])
    return root, proj


def _connect() -> sqlite3.Connection:
    return store_db.connect()


# ---------- 1. 三档切换行为（WIP 闸随档变化） ----------

def test_solo_default_wip_cap_is_one(pool):
    """缺省 = solo：同一 actor 认领第二件被拒（现状行为不变）。"""
    _run_json("--json", "next")
    rc, err = _run_json("--json", "next", expect=3)
    assert err["error"]["code"] == Code.TASK_ALREADY_CLAIMED.value
    assert err["error"]["details"]["wip_cap"] == 1


def test_fleet_preset_raises_wip_cap(pool):
    """fleet：同一 actor 可并行两件，第三件被拒。"""
    _run_json("--json", "config", "preset", "fleet")
    rc, first = _run_json("--json", "next")
    rc, second = _run_json("--json", "next")
    assert first["data"]["task"]["id"] != second["data"]["task"]["id"]
    rc, err = _run_json("--json", "next", expect=3)
    assert err["error"]["details"]["wip_cap"] == 2


def test_team_shares_fleet_wip_cap_and_adds_governance(pool):
    """team = fleet 基线 + 治理开关（所有权/审计留痕）。"""
    _run_json("--json", "config", "preset", "team")
    conn = _connect()
    eff = cfg.effective_config(conn)
    conn.close()
    assert eff["wip_max"] == 2
    assert eff["claim_racing"] and eff["claim_ownership"] and eff["audit_trail"]


def test_preset_switch_clears_overrides(pool):
    """切档即清空单项覆盖：档是组合的真相源，覆盖只在档内微调。"""
    _run_json("--json", "config", "preset", "fleet")
    _run_json("--json", "config", "set", "wip_max", "5")
    _run_json("--json", "config", "preset", "team")
    conn = _connect()
    eff = cfg.effective_config(conn)
    conn.close()
    assert eff["wip_max"] == 2
    assert eff["overrides"] == []


def test_override_only_touches_one_switch(pool):
    """单项覆盖只动一键：fleet 基线其余开关保持。"""
    _run_json("--json", "config", "preset", "fleet")
    _run_json("--json", "config", "set", "audit_trail", "on")
    conn = _connect()
    eff = cfg.effective_config(conn)
    conn.close()
    assert eff["audit_trail"] is True
    assert eff["claim_racing"] is True  # fleet 基线未被波及
    assert eff["overrides"] == ["audit_trail"]


def test_unset_override_restores_preset_default(pool):
    _run_json("--json", "config", "preset", "fleet")
    _run_json("--json", "config", "set", "wip_max", "5")
    _run_json("--json", "config", "unset", "wip_max")
    conn = _connect()
    assert cfg.next_wip_cap(conn) == 2
    conn.close()


# ---------- 2. config show 与实际行为一致 ----------

def test_config_show_matches_effective_behavior(pool):
    """show 渲染的 wip_max 与 next 实际执行的闸一致（fleet=2）。"""
    _run_json("--json", "config", "preset", "fleet")
    rc, shown = _run_json("--json", "config", "show")
    conn = _connect()
    eff = cfg.effective_config(conn)
    conn.close()
    assert shown["data"] == eff
    # 行为核对：show 说 cap=2，next 就真能连认 2 件
    assert shown["data"]["wip_max"] == 2
    ids = {_run_json("--json", "next")[1]["data"]["task"]["id"] for _ in range(2)}
    assert len(ids) == 2


def test_config_show_without_any_config_is_solo(pool):
    """从未写过配置的库，show 出来就是 solo 全关清单。"""
    rc, shown = _run_json("--json", "config", "show")
    data = shown["data"]
    assert data["preset"] == "solo"
    assert data["overrides"] == []
    assert all(v is False for k, v in data.items() if k in cfg.MECHANISMS)


# ---------- 3. 缺配置 = 全关（fail-closed） ----------

def test_missing_config_means_all_mechanisms_off():
    """meta 无任何配置行：机制全 off，wip 回落 1。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
    eff = cfg.effective_config(conn)
    assert eff["preset"] == "solo"
    assert all(v is False for k, v in eff.items() if k in cfg.MECHANISMS)
    assert cfg.next_wip_cap(conn) == 1
    conn.close()


def test_corrupt_preset_falls_back_to_solo_not_all_on():
    """存量脏档名回落 solo（fail-closed：绝不解释成「全开」）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
    conn.execute("INSERT INTO meta VALUES ('preset', 'yolo-everything-on')")
    eff = cfg.effective_config(conn)
    assert eff["preset"] == "solo"
    assert all(v is False for k, v in eff.items() if k in cfg.MECHANISMS)
    conn.close()


def test_corrupt_or_unknown_overrides_never_turn_things_on():
    """脏覆盖 JSON / 非白名单键 / 非法值：读取时按不存在处理，写入时拒绝。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
    conn.execute("INSERT INTO meta VALUES ('config_overrides', '{not json')")
    assert cfg.get_overrides(conn) == {}
    conn.execute("INSERT INTO meta VALUES ('preset', 'fleet')")
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('config_overrides', '{\"god_mode\": true}')")
    assert cfg.get_overrides(conn) == {}
    with pytest.raises(PoolError) as exc:
        cfg.set_override(conn, "god_mode", True)
    assert exc.value.code == Code.CONFIG_INVALID
    with pytest.raises(PoolError):
        cfg.set_override(conn, "wip_max", 0)
    with pytest.raises(PoolError):
        cfg.set_override(conn, "wip_max", "many")
    conn.close()


def test_unknown_preset_rejected_at_write(pool):
    conn = _connect()
    with pytest.raises(PoolError) as exc:
        cfg.set_preset(conn, "army")
    assert exc.value.code == Code.CONFIG_INVALID
    assert cfg.get_preset(conn) == "solo"
    conn.close()


# ---------- config 命令错误面 ----------

def test_config_set_bad_value_exit_code(pool):
    rc, err = _run_json("--json", "config", "set", "wip_max", "abc", expect=2)
    assert err["error"]["code"] == Code.CONFIG_INVALID.value
    rc, err = _run_json("--json", "config", "preset", "nope", expect=2)
    assert err["error"]["code"] == Code.CONFIG_INVALID.value
