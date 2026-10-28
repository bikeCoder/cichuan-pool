"""预设档配置层（路线图 D2 / #10854）：solo（默认）/ fleet / team 三档。

纪律（fail-closed）：
- 所有进阶机制缺省 = 关。配置缺失绝不等于全开——meta 表没有 preset 行
  时一律回落 solo，而不是放开任何机制。
- 只有 preset 白名单内的机制键才可被单项覆盖；未知键/非法值在写入时拒绝，
  在读取时（存量脏数据）按「关」处理并归一，绝不让脏数据变成开。

机制键是公开开关清单的唯一真相源；机制本体随路线图阶段逐个落地，
未落地的键先占位（值进 config show，行为面暂无差别）。
"""
from __future__ import annotations

import json
import sqlite3

from .errors import Code, PoolError

DEFAULT_PRESET = "solo"

_META_PRESET_KEY = "preset"
_META_OVERRIDES_KEY = "config_overrides"

# 机制键 → 人话说明（config show 逐项展开）。新增机制必须先在此登记。
MECHANISMS: dict[str, str] = {
    "claim_racing": "multi-agent racing claims on the same task",
    "wip_backpressure": "reject new claims while in-progress work exceeds the per-actor cap",
    "conflict_adjudication": "file-surface conflict adjudication between concurrent claims",
    "claim_ownership": "claim ownership binding across actors (team review basis)",
    "audit_trail": "extra audit events for every claim/release",
}

# wip_backpressure 的每 actor 上限：solo=1（一次只办一件，默认行为不变），
# fleet/team=2。单项覆盖可改，必须 >= 1。
WIP_CAP_BY_PRESET: dict[str, int] = {"solo": 1, "fleet": 2, "team": 2}


def _solo() -> dict[str, object]:
    return {k: False for k in MECHANISMS} | {"wip_max": WIP_CAP_BY_PRESET["solo"]}


def _fleet(extra: tuple[str, ...] = ()) -> dict[str, object]:
    base = _solo()
    base["wip_max"] = WIP_CAP_BY_PRESET["fleet"]
    for key in ("claim_racing", "wip_backpressure", "conflict_adjudication", *extra):
        base[key] = True
    return base


# 预设档 → 完整开关清单。真相源；config show 即此表与覆盖项的合并结果。
PRESETS: dict[str, dict[str, object]] = {
    "solo": _solo(),
    "fleet": _fleet(),
    "team": _fleet(extra=("claim_ownership", "audit_trail")),
}


def _validate_preset(name: str) -> str:
    if name not in PRESETS:
        raise PoolError(Code.CONFIG_INVALID,
                        f"unknown preset '{name}': one of {sorted(PRESETS)}",
                        {"preset": name})
    return name


def _validate_override(key: str, value: object) -> object:
    if key == "wip_max":
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise PoolError(Code.CONFIG_INVALID, "wip_max must be an integer >= 1",
                            {"key": key, "value": value})
        return value
    if key not in MECHANISMS:
        raise PoolError(Code.CONFIG_INVALID,
                        f"unknown mechanism '{key}': one of {sorted(MECHANISMS)}",
                        {"key": key})
    if not isinstance(value, bool):
        raise PoolError(Code.CONFIG_INVALID, f"{key} must be a boolean (on/off)",
                        {"key": key, "value": value})
    return value


def get_preset(conn: sqlite3.Connection) -> str:
    """当前档名。缺行/脏值一律回落 solo（fail-closed：缺失 ≠ 任何机制放开）。"""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (_META_PRESET_KEY,)).fetchone()
    if row is None:
        return DEFAULT_PRESET
    name = row["value"]
    return name if name in PRESETS else DEFAULT_PRESET


def set_preset(conn: sqlite3.Connection, name: str) -> None:
    """切换预设档。切换即清空全部单项覆盖（档是组合的真相源，覆盖只在档内微调）。"""
    _validate_preset(name)
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                 (_META_PRESET_KEY, name))
    conn.execute("DELETE FROM meta WHERE key = ?", (_META_OVERRIDES_KEY,))
    conn.commit()


def get_overrides(conn: sqlite3.Connection) -> dict[str, object]:
    """当前单项覆盖。脏 JSON / 非白名单键按不存在处理（宁缺勿错开）。"""
    row = conn.execute("SELECT value FROM meta WHERE key = ?",
                       (_META_OVERRIDES_KEY,)).fetchone()
    if row is None:
        return {}
    try:
        raw = json.loads(row["value"])
    except (TypeError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, object] = {}
    for key, value in raw.items():
        try:
            clean[key] = _validate_override(key, value)
        except PoolError:
            continue
    return clean


def set_override(conn: sqlite3.Connection, key: str, value: object) -> None:
    checked = _validate_override(key, value)
    overrides = get_overrides(conn)
    overrides[key] = checked
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                 (_META_OVERRIDES_KEY, json.dumps(overrides)))
    conn.commit()


def unset_override(conn: sqlite3.Connection, key: str) -> bool:
    overrides = get_overrides(conn)
    if key not in overrides:
        return False
    del overrides[key]
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                 (_META_OVERRIDES_KEY, json.dumps(overrides)))
    conn.commit()
    return True


def effective_config(conn: sqlite3.Connection) -> dict[str, object]:
    """当前生效的完整开关清单：预设档基线 + 单项覆盖。

    这是行为面的唯一读数——机制实现读这里，`pool config show` 也渲染这里，
    两边天然一致。
    """
    preset = get_preset(conn)
    merged = dict(PRESETS[preset])
    merged.update(get_overrides(conn))
    return {"preset": preset, "overrides": sorted(get_overrides(conn)), **merged}


def next_wip_cap(conn: sqlite3.Connection) -> int:
    """next 认领闸的每 actor 在办上限。缺配置 = 1（现状，不放开）。"""
    value = effective_config(conn)["wip_max"]
    return value if isinstance(value, int) and value >= 1 else WIP_CAP_BY_PRESET["solo"]
