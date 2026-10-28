"""迁移前自动备份与回滚（design-v1 §7「迁移备份」验收）。

备份 = 池库文件的逐字节拷贝（SQLite 单机锁下安全；V1 不做在线备份 API）。
回滚 = 迁移抛错时以备份覆盖原文件，保证「迁移失败可恢复备份」。
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from .paths import resolve_backup_dir, resolve_db_path


class MigrationError(RuntimeError):
    pass


def make_backup(db_path: str | Path | None = None, data_dir=None) -> Path:
    src = Path(db_path) if db_path else resolve_db_path()
    backup_dir = resolve_backup_dir(data_dir) if data_dir is not None else src.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = backup_dir / f"{src.stem}.pre-migration-{stamp}{src.suffix}"
    shutil.copy2(src, dst)
    return dst


def restore_backup(backup: Path, db_path: str | Path | None = None) -> None:
    src = Path(db_path) if db_path else resolve_db_path()
    # WAL/SHM 是旧连接的残留，回滚前一并清掉，避免覆盖后读到脏页
    for suffix in ("-wal", "-shm"):
        side = Path(str(src) + suffix)
        if side.exists():
            side.unlink()
    shutil.copy2(backup, src)


def upgrade(conn: sqlite3.Connection, *, db_path: str | Path | None = None) -> int:
    """把库从当前版本逐级迁到 SCHEMA_VERSION。任何一步失败即回滚到备份。

    空库（无文件或 0 字节）直接建 schema，不算迁移、不产备份。
    返回迁移后的 schema 版本。
    """
    from .db import SCHEMA_VERSION, create_schema, schema_version

    path = Path(db_path) if db_path else resolve_db_path()
    current = schema_version(conn)
    if current > SCHEMA_VERSION:
        raise MigrationError(
            f"pool schema version {current} is newer than supported {SCHEMA_VERSION}; "
            "Upgrade cichuan-pool first."
        )
    # 空库判定不能用文件大小（连接建立时 WAL pragma 已写入头部）：
    # v0 且无任何用户表 = 全新库，直接建 schema，不算迁移、不产备份。
    has_tables = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
    ).fetchone() is not None
    fresh = current == 0 and not has_tables
    if fresh or current == SCHEMA_VERSION:
        if fresh:
            create_schema(conn)
        return schema_version(conn)

    backup = make_backup(path)
    try:
        from . import migrations as m

        while schema_version(conn) < SCHEMA_VERSION:
            v = schema_version(conn)
            step = m.get_step(v)
            if step is None:
                raise MigrationError(f"missing migration step for v{v}")
            step(conn)
            newv = v + 1
            conn.execute(f"PRAGMA user_version = {newv}")
            conn.commit()
    except Exception:
        conn.close()
        restore_backup(backup, path)
        raise MigrationError(
            f"migration failed; restored from backup: {backup}"
        ) from None
    return schema_version(conn)
