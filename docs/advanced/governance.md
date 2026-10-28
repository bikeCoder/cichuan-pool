# Advanced path 4: Governance — rules when more than one actor shares the pool

> Preset: `team` · Commands: `pool config`, `POOL_ACTOR`, `pool export`
> Builds on: [concurrency.md](concurrency.md) (racing and caps).

## The incident

A pool shared by several agents produced a delivery claim from an agent that
had never touched the task — a second session "helpfully" closed out work it
hadn't done, registering a commit sha it had seen in a chat log. The claim
looked legitimate in the pool; only the event trail showed the actor
mismatch. The same week, an externally imported task list was fed straight to
agents, instructions included — task text is something an agent will *execute*,
and nobody had reviewed it.

Both failures are governance problems: who may act on a task, and what trail
exists when you need to ask that later.

## The mechanisms

### 1. Claim ownership — an actor can only close what it claimed

With `team` on, claiming and closing are bound to the same identity. Every
claim records `claimed_by`; `pool done` checks the caller's `POOL_ACTOR`
against it:

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

A live mismatch, rejected:

```console
$ POOL_ACTOR=alice pool next
Claimed #4: Fix the docs build
Reason: waited 0.0 days

$ POOL_ACTOR=bob pool done 4 --commit 190072b --json
{"ok": false, "error": {"code": "TASK_NOT_CLAIMED_BY_ACTOR",
 "message": "task #4 was claimed by alice; actor bob may not done it",
 "details": {"id": 4, "claimed_by": "alice"}}}
```

The ownership check is enforced by the state machine on the `done` path
regardless of preset — `team` is the *declaration* of the discipline: a
shared pool where actors are real identities, not defaults. (`solo` gets away
with `POOL_ACTOR` unset because there is only ever one actor to blame.)

### 2. Audit trail — the event ledger

Every lifecycle transition appends an event row: `added`, `claimed` (with
actor and the one-line selection reason), `done_pending` (with sha and
actor), `archived` (with the evidence tier). `pool export` writes the whole
ledger — projects, tasks, events — as a self-describing versioned JSONL file:

```console
$ pool export trail.jsonl
Exported 4 tasks / 12 events -> trail.jsonl
```

```json
{"type": "event", "id": 5, "task_id": 1, "kind": "done_pending",
 "at": "2026-10-28T23:26:36.224Z",
 "payload_json": "{\"sha\": \"190072b11d484f57a1d5c45068e42617a4c213f0\", \"actor\": \"solo\"}"}
```

When the question is "who claimed this, when, and on what grounds", the
answer is a `grep` away — no log aggregation, no server.

### 3. Untrusted imports — external task text is quarantined

Governance also covers what enters the pool. Tasks imported with `pool
import` are always marked `untrusted`: they are **read-only for agents**
(`pool next` flags them with `untrusted_readonly: true` in JSON and a loud
warning in human output) until a human reviews and approves them. Task text
is an instruction an agent may execute; imported text gets review before
execution, structurally, not by convention.

## Command surface recap

| Command | Role in this path |
|---|---|
| `pool config preset team` | fleet mechanics + ownership + audit declarations |
| `POOL_ACTOR=<name>` on every call | the identity the whole path rests on |
| `pool export <file>` | the append-only event ledger for review |
| `pool import <file>` | external tasks enter as `untrusted` (agent read-only) |

## When to turn it on

- The pool is written by more than one human-agent pair, or claimed by
  agents you don't sit behind. `team` makes identity and trail part of the
  workflow instead of an afterthought.
- You import tasks from anywhere you didn't write by hand.
- Solo practitioner: stay on `solo`; a one-actor audit trail already exists
  (events are always recorded) and the ownership check is already enforced.
  `team` adds declarations you don't need yet.
