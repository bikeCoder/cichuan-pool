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
| `pool mcp [--read-only]` | MCP server exposing the pool as native agent tools (stdio transport, no network; see [MCP server](#mcp-server) below) |
| `pool export <file>` / `pool import <file>` | Versioned JSONL backup / restore |

Selection order: effective score (highest first), then wait time, then task
id — stable and explainable. Filters narrow the set; they never reorder it.
By default one task is in progress at a time.

## Advanced guides: the four pain paths

Beyond the core loop, the pool grows along four paths — one per pain, one
guide each, mapped to a preset where one applies:

| Path | You feel this when | Read |
|---|---|---|
| **Concurrency** | two agents grabbed the same task | [docs/advanced/concurrency.md](docs/advanced/concurrency.md) (`fleet` preset) |
| **Scale** | the pool passed 100 tasks and you can't tell what's next | [docs/advanced/scale.md](docs/advanced/scale.md) |
| **Auditing** | did the agents actually deliver? | [docs/advanced/auditing.md](docs/advanced/auditing.md) |
| **Governance** | rules and trails for a shared pool | [docs/advanced/governance.md](docs/advanced/governance.md) (`team` preset) |

Each guide opens with a real incident from running a large internal pool,
explains the mechanism, walks the commands (every transcript was produced by
actually running them), and ends with criteria for when to switch the path
on. Chinese mirrors live under [docs/zh/advanced/](docs/zh/advanced/).
`pool --help` intentionally shows only the five core commands plus these four
entries — advanced commands (`config`, `board`, `doctor`, `mcp`, `export`,
`import`) stay executable and documented in the guides.

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

## MCP server

`pool mcp` starts a [Model Context Protocol](https://modelcontextprotocol.io)
server so MCP-native agents (Claude Code, Cursor, …) drive the pool with
native tools instead of shelling out to the CLI. It is a **thin wrapper**:
every tool forwards to the same code path as the CLI command, returns the
same JSON envelope, and uses the same `error.code` values — the CLI stays the
single source of truth.

| Tool | Access | Forwards to |
|---|---|---|
| `pool_next` | write | `pool next` (claiming mutates pool state) |
| `pool_add` | write | `pool add` |
| `pool_done` | write | `pool done` |
| `pool_sync` | write | `pool sync` |
| `pool_list` | read | read-only SELECT of all tasks (public fields) |

**Permission separation.** Every tool declares its access class and carries
the matching MCP `readOnlyHint` annotation, so hosts can auto-approve read
tools while gating write ones. Start the server with `--read-only` (or
`POOL_MCP_READ_ONLY=1`) to enforce it server-side: `tools/list` then only
advertises read tools and any write-tool call is rejected with
`MCP_WRITE_DISABLED`. Note that all four core-loop tools are write tools —
claiming (`pool_next`) and archiving (`pool_sync`) change pool state, so a
read-only server intentionally exposes just `pool_list`.

**Transport & network.** The only transport in this release is **stdio**:
the host spawns `pool mcp` as a child process and speaks newline-delimited
JSON-RPC 2.0 over stdin/stdout. The server never opens a socket — there is
no network surface at all (a test pins this). Remote transports and
authentication are explicitly out of scope until the hosted phase.

### Claude Code setup

Add to `.mcp.json` in your project root (or configure via `claude mcp add`):

```json
{
  "mcpServers": {
    "cichuan-pool": {
      "command": "pool",
      "args": ["mcp"],
      "env": { "POOL_ACTOR": "claude-code" }
    }
  }
}
```

`POOL_ACTOR` sets the claiming identity (defaults to `solo`). To run it
read-only (e.g. for a review-only agent), use `"args": ["mcp", "--read-only"]`.
`pool mcp` reads the same `--data-dir` / `POOL_DATA_DIR` as the CLI.

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
- The optional board binds to `127.0.0.1` by default; anything else is an
  explicit, detectable override. The MCP server uses stdio only and never
  opens a network socket.

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
