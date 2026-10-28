# Launch kit（阶段 A-07 冷启动材料草案）

> **状态：草稿，待人工定稿与拍板。** 本文件汇总 #10851 所需的全部素材；
> 转公开仓 / 发 PyPI / 三渠道发帖是不可逆动作，按 D17 须达 D11 发布线由人拍板执行。

## 0. D11 发布线对账（当前状态）

| 项 | 状态 |
|---|---|
| 核心闭环五命令可跑通（30 分钟内） | ✅ CI install-smoke 6 jobs 全绿（三 OS × py3.10/3.12，run 40718486889） |
| 对抗测试（未合并永不归档） | ✅ CI 机械钉死 |
| 英文 README + 演示段 | ✅ 顶部即核心闭环 |
| 信任模型 / 备份回滚 / AGENTS.md 片段 | ✅ |
| 中英叙事文 | ⬜ 草稿见 §1，需人工润色定稿 |
| 90 秒闭环演示 | ⬜ 录制脚本见 §2，需真人录制 |
| 转公开 / PyPI / 三渠道 | ⬜ 待拍板（§4 执行清单） |

## 1. 叙事文草稿

### 中文（即刻/V2EX 用）

**标题**：164 条积压教会我的事：给 AI agent 用的任务池，不该靠信任表运转

过去一年我同时指挥多个 AI agent 干活，积压池滚到 164 条。真正的灾难不是慢，
是**谎报完成**：agent 说做完了，commit 找不到；找到了，只在一条没人合并的
特性分支上。归档靠 run 收尾状态推断，误伤与漏放轮番上演。

cichuan-pool 的答案是把「完成」拆成两个动作：`done` 只是登记声明，
`sync` 拿 git 历史核账——commit 是默认分支祖先才自动归档，在特性分支上就
老实挂着「待确认」。任何人（或 agent）谎报 strong 证据，对抗测试直接红。

本地优先：一个 SQLite 文件就是全部状态，`export` 出版本化 JSONL 换机随走。
agent 接口优先：`--json` 稳定 envelope、16 个文档化错误码、认领必附一行
可解释理由。外部导入的任务一律 untrusted 只读——任务文本就是会被执行的指令，
这道闸不信任任何文件内标记。

（辞川——我们的 AI 小说创作平台——是第一个重度用户：它的 700+ 条机制债
与事故史都在这个池子上跑过。但这个工具本身不关心你写不写小说。）

### English (HN title + body sketch)

**Title**: Show HN: Cichuan-pool – a local-first task pool that verifies agent
deliveries against git

Body beats: 164-item backlog taught us agents misreport completion; done/sync
separation (claim vs evidence); git-fallback evidence adapter (ancestor of
default branch = strong, feature branch = weak, never fetches/writes your repo);
untrusted imports are read-only for agents by design; single SQLite file,
versioned JSONL export, auto-backup migrations; stable JSON envelope + 16
documented error codes + one-line explainable claim reasons. Apache-2.0,
zero runtime deps.

## 2. 90 秒演示脚本（shot list）

| 秒 | 画面 | 旁白要点 |
|---|---|---|
| 0-8 | 终端 `pool init` → `Pool ready:` | 零配置，一个文件就是池 |
| 8-20 | `pool add` ×3（真实任务文案） | 任务文本=给 agent 的指令 |
| 20-32 | `pool next` → 认领 + Reason 行 | 原子认领，理由可解释；重复 next 被拒 |
| 32-45 | 切编辑器/伪实现，git commit（subject 含 #1） | agent 干活 |
| 45-55 | `pool done 1 --commit <sha>` | done 只是声明 |
| 55-70 | `pool sync` → archived #1；再演示特性分支件 sync → unconfirmed | 核账分离：谎报不过闸 |
| 70-80 | dangling commit 对抗：sync 不归档 | 未合并永不归档 |
| 80-90 | `pool export` 一行 JSONL + `--json` envelope 特写 | 备份可校验，agent 接口稳定 |

## 3. 三渠道发布帖要点与度量

| 渠道 | 形态 | 初始度量记录 |
|---|---|---|
| HN | Show HN（英文稿 §1） | 发帖链接 + 发布日期 + 48h 点赞/评论数 |
| V2EX | 中文稿 + README 链接 | 同上 |
| 即刻 | 中文稿精简版 + 90 秒视频 | 同上 |

D11 三数基线：周活跃安装（PyPI 下载量代理）/ 首次归档耗时 / 7 日留存——
发布日起每周记录一次到本文件追加节。

## 4. 执行清单状态（2026-10-28 用户授权代执行后更新）

1. ⬜ 润色定稿 §1 两篇叙事文 + 录制 §2 演示视频（人工：真人媒体工作）
2. ✅ **仓已转 public**（2026-10-28，gh repo edit；未认证 API 复验 `private=false,
   visibility=public`：https://github.com/bikeCoder/cichuan-pool）
3. ✅ **已上 PyPI**（2026-10-29）：`cichuan_pool-0.1.0.dev0`（sdist+wheel，twine check
   PASSED）→ https://pypi.org/project/cichuan-pool/0.1.0.dev0/ ；凭据=~/.pypirc
   （用户提供）。终验：官方源干净 venv `pip install --pre cichuan-pool` →
   init/add/next/done/sync 全链路 ✓（假 sha 被 sync 正确拒为 unconfirmed）。
   注：预发布版默认 `pip install cichuan-pool` 不可见，需 `--pre`；正式 0.1.0 随
   D11 发布线上线。用户侧 pip 默认阿里云镜像，镜像同步有小时级延迟。
4. ⬜ 三渠道发帖并回填 §3 链接与日期（需社交账号）
5. ✅ 发布后复验完成：PyPI 官方源干净 venv 安装五命令全链路 ✓（见 3）；
   此前替代证据：CI install-smoke 真 runner 干净容器全绿 + 公开 sdist venv 冒烟。
