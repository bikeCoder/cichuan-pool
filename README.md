# cichuan-pool

**An agent-first task pool.** Local-first CLI for managing a backlog of tasks
that AI agents pick up, implement, and deliver — with evidence-based
verification instead of honor system.

- **Local-first**: your tasks live in a single SQLite database on your machine
  (`~/.cichuan-pool/` by default). No server, no account, no telemetry.
- **Agent-first**: stable JSON output (`--json`), documented error codes, and
  one-line human-readable reasons for every decision.
- **Evidence-based**: "done" is a claim; `sync` verifies it against the git
  history. An unmerged commit never gets archived.

Status: **v0 pre-release, under active development** (private until the V1
release line).

## The core loop

```text
init → add → next → (agent implements & git commits) → done <id> --commit <sha> → sync
```

`done` only *registers* a delivery claim. `sync` *verifies* it: a commit that
is an ancestor of the default branch is strong evidence and gets archived
automatically; a commit on a feature branch stays unconfirmed; a missing
object or mismatched repo is never archived.

```console
$ pool init
Pool ready: /home/you/.cichuan-pool

$ pool add "Fix the login timeout"
#1 added (candidate): Fix the login timeout

$ pool next
Claimed #1: Fix the login timeout
Reason: waited 0.0 days

$ pool done 1 --commit <sha>
#1 delivery registered, pending verification

$ pool sync --repo ~/src/myproject
archived #1: commit 1cfdf9fbba41 is on default branch main
```

When there is nothing claimable, `next` fails with a documented code instead
of pretending:

```console
$ pool next --json
{"ok": false, "error": {"code": "TASK_NOT_CLAIMABLE",
 "message": "no claimable candidate (filter or task status)", "details": {}}}
```

## Commands

| Command | What it does |
|---|---|
| `pool init` | Create the pool database, print the data root |
| `pool add <text>` | Create a candidate task (project identity from the git remote of your current repo) |
| `pool next [--tag ...]` | Atomically claim one task; returns the task plus a one-line selection reason |
| `pool done <id> --commit <sha>` | Register a delivery claim (task → `done_pending_merge`) |
| `pool sync [--repo PATH]` | Verify claims: archive strong evidence, keep the rest unconfirmed with reasons (grouped by strong/weak/none) |
| `pool doctor [--repo PATH]` | Read-only diagnosis: every pending claim falls into exactly one family — no sha / cross-repo (possible multi-landing) / strong / weak / none; weak items get two action hints (borrow an agent to verify, or confirm manually) |
| `pool board [--host H] [--port P]` | Optional local board (read-only, stdlib only): binds 127.0.0.1:8765 by default; a non-loopback `--host` prints an exposure warning |
| `pool export <file>` / `pool import <file>` | Versioned JSONL backup / restore |

Selection order: effective score (highest first), then wait time, then task
id — stable and explainable. Filters narrow the set; they never reorder it.
By default one task is in progress at a time.

## Presets (solo / fleet / team)

Don't configure individual switches — pick a preset and move on:

| Preset | For | What it turns on |
|---|---|---|
| `solo` (default) | one person, one agent | nothing — the plain core loop |
| `fleet` | several agents on one machine | claim racing, WIP backpressure (2 per actor), file-conflict adjudication |
| `team` | shared review discipline | everything in `fleet`, plus claim ownership and an audit trail |

```console
$ pool config preset fleet
Preset switched: fleet (overrides cleared)

$ pool config show
preset: fleet
  claim_racing: on
  ...
```

`pool config show` prints the full switch list of the current preset. Need one
tweak? Override a single switch (`pool config set audit_trail on`,
`pool config unset audit_trail`) — but presets, not switches, are what the
docs teach. Every advanced mechanism is **off by default**: a pool with no
configuration behaves exactly like plain `solo` (fail-closed).

## Machine interface

Add `--json` (before or after the subcommand) for a stable envelope:

```json
{"ok": true, "data": {"task": {"id": 1, "status": "claimed", "...": "..." }, "reason": "waited 0.0 days"}}
```

```json
{"ok": false, "error": {"code": "TASK_ALREADY_CLAIMED", "message": "...", "details": {"claimed_task_id": 1}}}
```

Agents must depend on `error.code`, never on `message`. Exit codes:
`0` success · `2` usage error · `3` expected business rejection ·
`4` environment/storage error.

Error codes: `POOL_NOT_INITIALIZED` `POOL_ALREADY_INITIALIZED` `POOL_EMPTY`
`TASK_NOT_FOUND` `TASK_NOT_CLAIMABLE` `TASK_ALREADY_CLAIMED`
`TASK_NOT_CLAIMED_BY_ACTOR` `DELIVERY_SHA_INVALID` `EVIDENCE_UNAVAILABLE`
`DELIVERY_UNCONFIRMED` `PROJECT_MISMATCH` `PROJECT_UNRESOLVED`
`CONFIG_INVALID` `DB_LOCKED` `IMPORT_FORMAT_UNSUPPORTED` `IMPORT_CONFLICT`
`USAGE`.

## Trust model (read this before importing tasks)

**Task text is an instruction an agent may execute.** Only put tasks in the
pool that you trust.

- Tasks imported via `pool import` are always marked `untrusted` — regardless
  of what the file says. An `untrusted` task is **read-only for agents**;
  `pool next` flags it explicitly (`untrusted_readonly: true` in JSON, a
  warning line in human output). A human must review and approve it before
  any agent acts on it.
- Evidence probing **never writes to your repositories**: the git adapter
  reads refs and objects only. It never fetches, never rewrites refs, never
  touches the working tree.
- The optional board / MCP server binds to `127.0.0.1` by default; anything
  else is an explicit, detectable override.

## Backup and rollback

- `pool export dump.jsonl` writes a self-describing, versioned JSONL file
  (one JSON object per line: `project` / `task` / `event` rows).
- `pool import dump.jsonl` refuses unknown format versions
  (`IMPORT_FORMAT_UNSUPPORTED`), never overwrites conflicting task ids
  (`IMPORT_CONFLICT` with a per-item report), and prints added/skipped/
  conflict counts you can reconcile against the file.
- Every schema migration takes an automatic file-level backup of the database
  first; a failed migration restores the backup and reports where it is.
  A database with a *newer* schema version refuses to open rather than
  guessing.

## Contributing

- `pip install -e .[dev]` then `pytest` (no third-party runtime dependencies;
  tests use temporary repositories only — no network, no hub, no real user
  repos).
- Apache-2.0. Issues and PRs welcome once the repo goes public.

## Design docs

The V1 technical contract (public schema, evidence tiers, state machine,
invariants) lives in the internal design repo during the private period and
ships with the public release. Chinese docs: `docs/` (this README is the
English source of truth).
