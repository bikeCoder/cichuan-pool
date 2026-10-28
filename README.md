# cichuan-pool

agent-first 任务池（本地优先，CLI 核心 + 可选看板）。**V1 开发中，未发布。**

核心闭环（design-v1 §1）：

```text
init → add → next →（agent 实现并 git commit）→ done <id> --commit <sha> → sync
```

- 数据根默认 `~/.cichuan-pool/`（`--data-dir` / `POOL_DATA_DIR` 覆盖）
- pip 包名 `cichuan-pool`，命令名 `pool`
- 技术契约：内部仓 `cichuan-backlog/docs/product/design-v1.md`（公开后随仓迁移）
- License：Apache-2.0

## 开发

```bash
pip install -e .[dev]
pytest
```

## 包边界

```text
pool/core     池件生命周期、迁移、导入导出（不 import 任何内部 hub 模块）
pool/store    SQLite、事务、备份
pool/evidence 证据契约与适配器（git 兜底；novelplatform 为可选 extras）
pool/cli      命令解析与人话/JSON 渲染
pool/board    可选本地看板适配层
```
