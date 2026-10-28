# 进阶路径 1：并发——多个 agent，一个池

> 预设档：`fleet` · 命令：`pool next`、`pool config` · 相关：[governance.md](governance.md)（身份与评审纪律）。

## 事故开篇

某个早晨，三个 agent 窗口同时对同一个池开工。其中两个窗口各自独立选中了同一件任务——都觉得它「显然是下一件」——各自产出了一笔互相冲突的交付。第三个窗口更隐蔽：没有任何机制阻止它连领十件，在办队列被它囤走一半，其余任务全部饿死。

两个失败都不需要恶意。agent 之间不会自发协调——除非**池子**强制：先认领者必须原子获胜，单一 actor 不许饿死其他席位。

## 机制讲解

### 1. 认领竞速是原子的——永远开着

`pool next` 在单个 SQLite `BEGIN IMMEDIATE` 事务里完成「选件 + 翻状态」。两个 agent 同一瞬间调 `next` 不可能拿到同一件：第二个的写入在数据库层面被拒（`status = 'candidate'` 已不匹配），它只会拿到次优的那件。不存在可以输掉竞速的「先查后改」窗口，也没有需要打开的开关——这是核心闭环，任何预设档下都生效。

### 2. WIP 背压——按 actor 的在办上限

池子的健康度取决于最慢的消费者。`fleet` 把上限从 solo 的 1 提到**每 actor 2 件在办**。触顶后继续认领会被拒绝并返回文档化错误码——agent 必须先 `pool done` 再认领：

```console
$ pool config preset fleet
Preset switched: fleet (overrides cleared)

$ pool config show
preset: fleet
  claim_racing: on
  wip_backpressure: on
  conflict_adjudication: on
  claim_ownership: off
  audit_trail: off
  wip_max: 2
```

两个 agent 竞速同一池的实况：

```console
$ POOL_ACTOR=agent-1 pool next
Claimed #1: Fix login timeout
Reason: oldest unscored (waited 0.0 days); ties broken by lowest id

$ POOL_ACTOR=agent-2 pool next
Claimed #2: Add export tests
Reason: oldest unscored (waited 0.0 days); ties broken by lowest id

$ POOL_ACTOR=agent-1 pool next
Claimed #3: Write quickstart
Reason: oldest unscored (waited 0.0 days); ties broken by lowest id

$ POOL_ACTOR=agent-1 pool next --json
{"ok": false, "error": {"code": "TASK_ALREADY_CLAIMED",
 "message": "WIP cap reached (2): task #1 is already in progress (run `pool done` first); not claiming more",
 "details": {"claimed_task_id": 1, "wip_cap": 2}}}
```

注意 details：错误点名了**最老**的在办件，agent 因此知道先办哪件。上限**按 actor 计**（`POOL_ACTOR`），不是全局——第三个 agent 加入照常认领。

不改档微调上限：

```console
$ pool config set wip_max 3
$ pool config unset wip_max     # 回到档默认（2）
```

### 3. 文件面冲突裁决——已声明，尚未强制

`fleet` 同时打开 `conflict_adjudication` 开关：声明并发认领应按文件面重叠裁决（两个 agent 都在改 `server/routes/` 与改不相干目录是两种不同的失败）。该开关目前先占住配置面；强制本体按路线图在后续阶段落地。在那之前的实务缓解正是 WIP 上限 + 小而聚焦的任务——上限存在的理由也在于此。

## 命令面速查

| 命令 | 在本路径中的角色 |
|---|---|
| `pool config preset fleet` | 打开竞速 + 背压 + 冲突裁决开关 |
| `pool config show` | 展开当前档完整开关清单 |
| `POOL_ACTOR=<name> pool next` | 以具名 agent 认领（上限的计数单位） |
| `pool config set wip_max <n>` | 每 actor 上限单项覆盖，`unset` 撤回 |

## 何时开启

- 两个及以上 agent（或 agent 窗口）共用一个池——两个终端标签页也算。solo 的上限 1 就是只有一个座位的 fleet。
- 出现过重复劳动或饿死队列。两件事都只隔着一句 `config preset fleet`。
- 只有恰好一个 agent 时留在 `solo`；这些开关在此不加任何东西。
