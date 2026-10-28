# 进阶路径 4：治理——多 actor 共池时的规矩

> 预设档：`team` · 命令：`pool config`、`POOL_ACTOR`、`pool export`
> 前置：[concurrency.md](concurrency.md)（竞速与上限）。

## 事故开篇

一个多人共用的池里，出现了一份来自「从未碰过该任务」的 agent 的交付声明——另一个会话「热心地」替别人收了尾，把在聊天记录里看到的 commit sha 登记了上去。声明在池里看起来完全合法；只有事件留痕暴露了 actor 错配。同一周，一份外部导入的任务清单被直接喂给了 agent，指令原文都在里面——任务文本是 agent 会**执行**的东西，却没有任何人审过。

两个失败都是治理问题：谁可以对一件任务行动，以及事后需要追问时留了什么痕。

## 机制讲解

### 1. 认领所有权——谁认领谁才能销

`team` 档下，认领与销账绑定同一身份。每次认领记录 `claimed_by`；`pool done` 用调用方的 `POOL_ACTOR` 核对：

```console
$ pool config preset team
Preset switched: team (overrides cleared)

$ pool config show
preset: team
  claim_racing: on
  wip_backpressure: on
  conflict_adjudication: on
  claim_ownership: on
  audit_trail: on
  wip_max: 2
```

一次实况错配被拒：

```console
$ POOL_ACTOR=alice pool next
Claimed #4: Fix the docs build
Reason: waited 0.0 days

$ POOL_ACTOR=bob pool done 4 --commit 190072b --json
{"ok": false, "error": {"code": "TASK_NOT_CLAIMED_BY_ACTOR",
 "message": "task #4 was claimed by alice; actor bob may not done it",
 "details": {"id": 4, "claimed_by": "alice"}}}
```

所有权校验由状态机在 `done` 路径上无条件强制——`team` 是这条纪律的**声明**：共享池里 actor 是真实身份而非默认值。（`solo` 敢让 `POOL_ACTOR` 缺省，是因为永远只有一个 actor 可追责。）

### 2. 审计留痕——事件账本

每个生命周期迁移都追加事件行：`added`、`claimed`（含 actor 与一行选择理由）、`done_pending`（含 sha 与 actor）、`archived`（含证据档位）。`pool export` 把整本账——项目、任务、事件——写成自带版本描述的 JSONL：

```console
$ pool export trail.jsonl
Exported 4 tasks / 12 events -> trail.jsonl
```

```json
{"type": "event", "id": 5, "task_id": 1, "kind": "done_pending",
 "at": "2026-10-28T23:26:36.224Z",
 "payload_json": "{\"sha\": \"190072b11d484f57a1d5c45068e42617a4c213f0\", \"actor\": \"solo\"}"}
```

「这是谁、何时、凭什么认领的」——一条 `grep` 就有答案，不需要日志聚合，不需要服务器。

### 3. untrusted 导入——外来任务文本先隔离

治理也覆盖入池口。`pool import` 导入的任务一律标 `untrusted`：对 agent **只读**（`pool next` 在 JSON 里给出 `untrusted_readonly: true`，人话输出有显著警告），直到有人复核放行。任务文本是 agent 可能执行的指令；外来文本先审后执行——这是结构保证，不是约定俗成。

## 命令面速查

| 命令 | 在本路径中的角色 |
|---|---|
| `pool config preset team` | fleet 机制 + 所有权 + 审计声明 |
| 每次调用带 `POOL_ACTOR=<name>` | 整条路径赖以成立的身份 |
| `pool export <file>` | 追加式事件账本，供评审 |
| `pool import <file>` | 外来任务一律 `untrusted` 入池（agent 只读） |

## 何时开启

- 池子由多个人-agent 对写入，或认领方是你盯不过来的 agent。`team` 让身份与留痕成为工作流的一部分而非事后补录。
- 从任何非手写来源导入任务。
- 单人独自使用：留在 `solo`。单 actor 的审计留痕本来就存在（事件永远在记），所有权校验本来就在强制。`team` 加的是你还不需要的声明。
