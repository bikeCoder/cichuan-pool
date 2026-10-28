# Advanced path 1: Concurrency — several agents, one pool

> Preset: `fleet` · Commands: `pool next`, `pool config` · Related guide:
> [governance.md](governance.md) for identities and review discipline.

## The incident

Three agent windows were running against the same backlog one morning. Two of
them independently picked the same task — both saw it as "the obvious next
thing" — and produced two conflicting commits for it. A third window, run by
the same operator, hoarded half the actionable queue: nothing stopped it from
claiming ten tasks in a row, so everything else starved while half the claims
sat idle in its session.

Neither failure needed malice. Agents don't coordinate unless the *pool* makes
them: whoever claims first must win atomically, and one actor must not be able
to starve the rest.

## The mechanisms

### 1. Claim racing is atomic — always

`pool next` selects a task and flips its status to `claimed` inside a single
SQLite `BEGIN IMMEDIATE` transaction. Two agents calling `next` at the same
instant can never receive the same task: the second one's write is rejected at
the database level (`status = 'candidate'` no longer matches) and it simply
gets the next-best task. There is no check-then-act window to lose a race
through, and no flag to turn on — this is the core loop, on in every preset.

### 2. WIP backpressure — the per-actor cap

A pool is only as healthy as its slowest consumer. `fleet` raises the *cap*
from solo's 1 to **2 tasks in progress per actor**. When an actor hits the
cap, further claims are rejected with a documented code — the agent must
finish (`pool done`) before claiming more:

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

A live session with two agents racing on the same pool:

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

Note the details: the error names the *oldest* in-progress task, so an agent
knows exactly what to finish first. The cap is **per actor** (`POOL_ACTOR`),
not global — a third agent joining the pool claims freely.

Tune the cap per pool without leaving the preset:

```console
$ pool config set wip_max 3
$ pool config unset wip_max     # back to the preset default (2)
```

### 3. Conflict adjudication — declared, not yet enforced

`fleet` also turns on the `conflict_adjudication` switch: the declaration that
concurrent claims should be adjudicated on file-surface overlap (two agents
both editing `server/routes/` is a different failure than two agents touching
disjoint directories). The switch reserves the config surface today; the
enforcement itself lands in a later stage of the roadmap. Until then the
practical mitigation is the WIP cap plus small, focused tasks — which is also
why the cap exists.

## Command surface recap

| Command | Role in this path |
|---|---|
| `pool config preset fleet` | enable racing + backpressure + adjudication switches |
| `pool config show` | see the full switch list of the current preset |
| `POOL_ACTOR=<name> pool next` | claim as a named agent (the unit the cap counts) |
| `pool config set wip_max <n>` | per-actor cap override, `unset` to revert |

## When to turn it on

- Two or more agents (or agent windows) share one pool — even two terminal
  tabs count. Solo's cap of 1 is just fleet with one seat.
- You have ever seen duplicated work or a starved queue. Both are one
  `config preset fleet` away from structurally impossible.
- Stay on `solo` while exactly one agent runs against the pool; the switches
  add nothing there.
