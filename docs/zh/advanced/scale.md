# 进阶路径 2：规模——池过 100 件之后

> 命令：`pool add --tag`、`pool next [--tag]`、`pool board`、`pool doctor`
> 预设档：无需——本路径是行为用法，不是开关。

## 事故开篇

一个内部池积到 164 件待办后停止了作为队列的职能。没人答得上「下一件做什么」——每个答案都要读半个池子。更糟的是，其中相当一部分**根本不是待办**：agent 早就干完了，只是核账积压从未清理，干完的活和待办的活在池里长得一模一样。池子不是慢慢变慢的；它直接没人用了——一个你不敢信的队列，比没有队列更糟。

解法不是换更聪明的人，而是让池子机械地回答两个问题：**下一件是哪件**、**哪些件在假装待办**（后者是[审计](auditing.md)路径；本页讲第一个）。

## 机制讲解

### 1. 选件是公开公式，不是玄学

`pool next` 永远按下面顺序挑：

1. **有效评分，高者优先**（评分由你自己的工具经公开 `score` 字段写入）；
2. **等待时长**——未评分件中，**最老**的候选胜出；
3. **最小件号**做最后平手裁决。

并且打印一行自我解释：

```console
$ pool next
Claimed #1: Bump dependencies
Reason: oldest unscored (waited 0.0 days); ties broken by lowest id
```

第二条规则**就是**老化通道：没人挑的未评分件不会下沉——它会上浮。一件被冷落的候选放了一阵之后：

```console
$ pool next
Claimed #2: Fix flaky test
Reason: oldest unscored (waited 12.0 days); ties broken by lowest id
```

没有任何东西会在池底无声腐烂。一件真正没人要的任务会爬到队首然后被认领或删除；一件只是被遗忘的任务，池子免费帮你浮出水面。

### 2. 过滤只缩集，绝不重排

标签是百件池保持可导航的手段。`--tag` 在公式运行**之前**对候选集求交，所以过滤后的认领遵守同一套规则、打印同样格式的理由：

```console
$ pool next --tag docs
Claimed #9: Document the CLI
Reason: waited 0.0 days
```

过滤集为空时——无论真枯竭还是已被认领——`next` 返回文档化错误码而不是自作主张挑别的：

```console
$ pool next --tag docs --json
{"ok": false, "error": {"code": "TASK_NOT_CLAIMABLE",
 "message": "no claimable candidate (filter or task status)", "details": {}}}
```

实践中有效的纪律：`add` 时打**少量**耐久标签（`docs`、`perf`、`infra`…），agent 按单一标签认领保持专注。当你发明第六个标签时，池子在告诉你任务本身太含糊。

### 3. 看板：只读全景

`pool board` 在 `127.0.0.1:8765` 起一个本地只读视图（纯标准库，默认不开任何网络面）：

```console
$ pool board
Board serving http://127.0.0.1:8765 (read-only; Ctrl+C to stop)
```

用于每周巡检（「什么在老化？谁认领了什么？」），不用于逐件循环——agent 走 `next` 认领，人只看板。要机器可读的状态计数，`pool doctor --json` 直接打印全池 `by_status`，无需开浏览器。

## 命令面速查

| 命令 | 在本路径中的角色 |
|---|---|
| `pool add <text> --tag <t>` | 入池时打标，过滤器后面才有的用 |
| `pool next [--tag ...]` | 按公开公式认领，附一行理由 |
| `pool board` | 全池只读本地看板 |
| `pool doctor` | 状态计数；其余见 [auditing.md](auditing.md) |

## 何时上心

- 待办过几十件，或第一次「下一件做什么」比干活还费时。公式与标签本来就在——本路径讲的是**用起来**。
- 评分分流是可选项：不评分就靠等待老化兜底；某件确实比年龄更重要时再打分。
- 积压持续增长而 `done`/`sync` 跟不上，那是[审计路径](auditing.md)的事，不是排序问题——先清账本。
