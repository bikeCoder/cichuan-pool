# 进阶路径 3：审计——agent 到底交付了没有？

> 命令：`pool done`、`pool sync`、`pool doctor`
> 预设档：无需——核验是核心能力，本路径讲的是怎么读它。

## 事故开篇

同一季度的两条审计发现，都来自一个大内部池的运行史：

1. **run 状态冒充了任务状态。** 归档准入信的是「持有该件的 run 到了终态」——run 记账与任务事实对不上时，164 件堆进了核账积压。更糟的是，强**件级**证据（commit 明明就躺在默认分支上）被毫不相干的 run 记账扣着不放。run 的状态不是关于任务的；commit 才是。
2. **跨仓探测造出死档。** agent 往一个仓交付，池子却在另一个仓探测；错配无声地产出了没人能追溯的「已交付」。跨仓交付必须**可见**，绝不能被悄悄销账。

两条发现收敛成同一条规则：**归档由件级证据对 git 判定，不足强证据的一律摆出来，不许默认。**（这个池子起步于一个小说创作平台 agent 舰队的内部工具，上述审计每周都在跑；这里讲的是其中通用的机制。）

## 机制：声明 vs 事实

`pool done` 记录 agent 的**声明**；`pool sync` 核对**事实**——该 commit 是否是交付仓默认分支的祖先？三档证据，硬性不对称：

- **strong**——commit 在默认分支上：`sync` 自动归档。
- **weak**——commit 存在但只在非默认分支：**永不**自动归档，附两条动作提示。
- **none**——对象缺失、仓不可读、探测出错：永不归档，交人工。

谎报 strong 是测试套件的失败（对抗夹具钉死四种情形：已合并 / 未合并 / 仅分支 / 无 sha）。漏报允许——只损失效率，不损失完整性。`sync` 幂等：重跑绝不重复归档。

## `pool doctor`：五族分报，全程只读

`sync` 会改状态（归档强证据）。`pool doctor` 跑同一套证据探测但**不写任何东西**，把每件待核账件分进且只分进一个族：

```console
$ pool doctor --repo ~/src/myapp
pool doctor — 3 tasks (done_pending_merge 3)
pending verification: 3
strong (sync will archive) (1):
  #1 Fix the login timeout: commit 190072b11d48 is on default branch main
weak (needs confirm) (1):
  #2 Add export tests: commit 05c420f9fa48 only on non-default branch(es) feature; not merged
    - borrow an agent to verify: have an agent merge the branch or re-check the commit, then re-run `pool sync --repo <repo>`
    - human confirm: inspect refs yourself (`git branch --contains <sha>`); weak evidence is never auto-archived
none (needs confirm) (1):
  #3 Document the evidence tiers: commit 2c835dd4153f is on no branch (dangling commit)
```

| 族 | 含义 | 处置 |
|---|---|---|
| `no_sha` | 待核账但没有登记交付 sha | 异常——重跑 `pool done <id> --commit <sha>` |
| `cross_repo` | 探测仓身份 ≠ 任务项目身份 | 疑似多落点交付：人工对账，V1 无自动路径 |
| `strong` | 已在默认分支；`sync` 会归档 | 直接跑 `pool sync` |
| `weak` | 存在但未合并 | 合并分支，或人工确认 |
| `none` | 游离 commit / 不可读 / 探测错 | 找到 commit，或驳回声明 |

两条事故发现直接映射进设计：强证据赢过一切 run 记账（`strong` 族），跨仓交付隔离进自己的族而不是被销掉（`cross_repo` 族）。

## `pool sync`：每周收账

```console
$ pool sync --repo ~/src/myapp
archived #1: commit 190072b11d48 is on default branch main
weak evidence (needs confirm):
  #2: commit 05c420f9fa48 only on non-default branch(es) feature; not merged
no evidence (needs confirm):
  #3: commit 2c835dd4153f is on no branch (dangling commit)
```

合并特性分支（或处置游离 commit）后重跑 `sync`，只有新变强的件会归档。JSON envelope（`--json`）把 `unconfirmed` 按同样的 `tier` 字段分组，定时夜间任务可以**按族**告警，不用解析人话。

## 命令面速查

| 命令 | 在本路径中的角色 |
|---|---|
| `pool done <id> --commit <sha>` | 登记声明（必做；commit subject 里的 `#id` 不算数） |
| `pool sync [--repo PATH]` | 核验并归档强证据；其余按档摆出 |
| `pool doctor [--repo PATH]` | 只读五族报告；随时可跑 |
| `pool export trail.jsonl` | 全量事件账本，供更深追查 |

## 何时上心

- 不止一个 agent，或任何一个你没盯着干的 agent。「done」一旦是别人的话，你就需要 `sync`。
- 把 `pool doctor` 当评审会的只读预检：它告诉你**什么将要**归档，而一行都还没写。
- 从每周一次开始：评审时 `pool sync`，报告异常时 `pool doctor`。`no_sha` 与 `cross_repo` 出现当天就该看一眼——它们是无声失败的两种形状。
