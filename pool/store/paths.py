"""数据根解析（design-v1 §3.1）：默认 ~/.cichuan-pool/pool.db，可参数/环境覆盖。

本模块是 core 唯一触达文件系统路径的地方；不得 import 任何内部 hub 概念
（CICHUAN_RUNS_DIR 等）。
"""
from __future__ import annotations

import os
from pathlib import Path

DB_FILENAME = "pool.db"
BACKUP_DIRNAME = "backups"
ENV_DATA_DIR = "POOL_DATA_DIR"


def default_data_dir() -> Path:
    env = os.environ.get(ENV_DATA_DIR)
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cichuan-pool"


def resolve_db_path(data_dir: str | os.PathLike[str] | None = None) -> Path:
    root = Path(data_dir).expanduser() if data_dir else default_data_dir()
    return root / DB_FILENAME


def resolve_backup_dir(data_dir: str | os.PathLike[str] | None = None) -> Path:
    root = Path(data_dir).expanduser() if data_dir else default_data_dir()
    return root / BACKUP_DIRNAME
