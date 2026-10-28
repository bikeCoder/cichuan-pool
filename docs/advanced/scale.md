# Advanced path 2: Scale — when the pool passes 100 tasks

> Commands: `pool add --tag`, `pool next [--tag]`, `pool board`, `pool doctor`
> Preset: none required — this path is behavior, not switches.

## The incident

An internal pool crossed 164 pending items and stopped functioning as a queue.
Nobody could answer "what should I do next?" — every answer required reading
half the backlog. Worse, a large share of those items were *not actually
open work*: agents had long finished them, but the reconciliation backlog had
never been cleared, so done work and open work were visually identical. The
pool didn't slow down gradually; it stopped being used, because a queue you
can't trust is worse than no queue.

The fix was not a smarter human. It was making the pool answer two questions
mechanically: **which one is next** and **which ones are lying about being
open** (the latter is the [auditing](auditing.md) path; this page is about
the first).

## The mechanisms

### 1. Selection is a published formula, not a vibe

`pool next` always picks by:

1. **effective score, highest first** (tasks scored by your own tooling via
   the public `score` field);
2. **wait time** — among unscored tasks, the *oldest* candidate wins;
3. **lowest task id** as the final tie-break.

And it prints one line explaining itself:

```console
$ pool next
Claimed #1: Bump dependencies
Reason: oldest unscored (waited 0.0 days); ties broken by lowest id
```

The second rule *is* the aging channel: an unscored task that nobody picks
does not sink — it floats. After a quiet candidate sits for a while:

```console
$ pool next
Claimed #2: Fix flaky test
Reason: oldest unscored (waited 12.0 days); ties broken by lowest id
```

Nothing rots silently at the bottom of the pool. If a task is genuinely
unwanted, you will see it climb to the top and get claimed-or-deleted; if it
is merely forgotten, the pool surfaces it for free.

### 2. Filters narrow, they never reorder

Tags are how a 100+-item pool stays navigable. `--tag` intersects the
candidate set before the formula runs, so a filtered claim follows the same
rules and prints the same style of reason:

```console
$ pool next --tag docs
Claimed #9: Document the CLI
Reason: waited 0.0 days
```

When a filtered set is empty — either genuinely exhausted or already claimed —
`next` fails with a documented code instead of picking something else:

```console
$ pool next --tag docs --json
{"ok": false, "error": {"code": "TASK_NOT_CLAIMABLE",
 "message": "no claimable candidate (filter or task status)", "details": {}}}
```

Discipline that works in practice: put a *small* number of durable tags on
tasks at `add` time (`docs`, `perf`, `infra`…), and let agents claim through
one tag for focus work. If you find yourself inventing a sixth tag, the pool
is telling you the tasks are too vague.

### 3. The board: read-only overview

`pool board` serves a local, read-only view of the whole pool on
`127.0.0.1:8765` (stdlib only, no network surface by default):

```console
$ pool board
Board serving http://127.0.0.1:8765 (read-only; Ctrl+C to stop)
```

Use it for the weekly look ("what's aging? what's claimed by whom?"), not for
the per-task loop — agents claim through `next`, humans glance through the
board. For machine-readable status counts, `pool doctor --json` prints
`by_status` for the whole pool without opening a browser.

## Command surface recap

| Command | Role in this path |
|---|---|
| `pool add <text> --tag <t>` | tag at entry, so filters work later |
| `pool next [--tag ...]` | claim by the published formula, with a reason |
| `pool board` | read-only local overview of the whole pool |
| `pool doctor` | status counts; see [auditing.md](auditing.md) for the rest |

## When to care

- Past a few dozen open items, or the first time "what's next?" takes longer
  than the work. The formula and tags are already on — this path is about
  *using* them.
- Score-based triage is opt-in: leave tasks unscored and wait-time aging does
  the job; once a task matters more than its age, score it.
- A backlog that keeps growing while `done`/`sync` lag is the [auditing
  path](auditing.md), not a sorting problem — clean the ledger first.
