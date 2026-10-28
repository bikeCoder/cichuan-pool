# Advanced path 3: Auditing — did the agents actually deliver?

> Commands: `pool done`, `pool sync`, `pool doctor`
> Preset: none required — verification is core, this path is about reading it.

## The incident

Two audit findings, from the same season of running a large internal pool:

1. **Run state was masquerading as task state.** Archival admission trusted
   "the run that owned this task reached a terminal state" — and 164 items
   piled up in a reconciliation backlog because run bookkeeping and task facts
   disagreed. Worse, strong *task-level* evidence (the commit was sitting
   right there on the default branch) was being held hostage by unrelated run
   bookkeeping. A run's status is not a fact about a task; the commit is.
2. **Cross-repo probing created dead archives.** An agent delivered into one
   repository while the pool probed another; the mismatch silently produced
   archives nobody could trace — "delivered" items with no reachable commit.
   Delivery across repositories must be *visible*, never silently reconciled.

Both findings shaped the same rule: **archival is decided by item-level
evidence against git, and anything short of strong evidence is shown, not
assumed.** (This pool began as the internal tooling of a fiction-writing
platform's agent fleet, where these audits were run weekly; the mechanism is
the general one described here.)

## The mechanism: claims vs. facts

`pool done` records the agent's *claim*; `pool sync` checks the *fact* — is
that commit an ancestor of the default branch in the delivery repo? Three
tiers, with hard asymmetry:

- **strong** — commit on the default branch: auto-archived by `sync`.
- **weak** — commit exists but only on non-default branches: *never*
  auto-archived. Shown with two action hints.
- **none** — object missing, repo unreadable, probe error: never archived,
  shown for human action.

Over-reporting strong evidence is a test-suite failure by design
(adversarial fixtures pin the four cases: merged / unmerged / branch-only /
no sha). Under-reporting is allowed — it only costs efficiency, never
integrity. `sync` is idempotent: re-running never double-archives.

## `pool doctor`: the five families, read-only

`sync` mutates (archives strong evidence). `pool doctor` runs the same
evidence probing **without writing anything** and sorts every pending item
into exactly one family:

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

| Family | Meaning | What to do |
|---|---|---|
| `no_sha` | pending but no delivery sha registered | abnormal — re-run `pool done <id> --commit <sha>` |
| `cross_repo` | probe repo's identity ≠ the task's project | possible multi-landing delivery: reconcile by hand, V1 has no auto path |
| `strong` | in default branch; `sync` will archive | just run `pool sync` |
| `weak` | exists, unmerged | merge the branch, or confirm manually |
| `none` | dangling commit / unreadable / probe error | locate the commit, or reject the claim |

The two incident findings map directly onto the design: strong evidence wins
regardless of any run bookkeeping (family `strong`), and cross-repo
deliveries are quarantined into their own family instead of being reconciled
away.

## `pool sync`: the weekly close

```console
$ pool sync --repo ~/src/myapp
archived #1: commit 190072b11d48 is on default branch main
weak evidence (needs confirm):
  #2: commit 05c420f9fa48 only on non-default branch(es) feature; not merged
no evidence (needs confirm):
  #3: commit 2c835dd4153f is on no branch (dangling commit)
```

After merging the feature branch (or resolving the dangling commit), re-run
`sync`; only the newly-strong items archive. The JSON envelope (`--json`)
groups `unconfirmed` entries with the same `tier` field, so a scheduled
nightly job can page on *families* rather than parsing prose.

## Command surface recap

| Command | Role in this path |
|---|---|
| `pool done <id> --commit <sha>` | register the claim (required; the `#id` in a commit subject alone is not) |
| `pool sync [--repo PATH]` | verify and archive strong evidence; report the rest by tier |
| `pool doctor [--repo PATH]` | read-only five-family report; safe to run anytime |
| `pool export trail.jsonl` | the full event ledger for deeper forensics |

## When to care

- More than one agent, or any agent you didn't personally watch. The moment
  "done" is someone else's word, you need `sync`.
- Make `pool doctor` the read-only pre-flight of a review session: it tells
  you what *will* archive before anything is written.
- Weekly cadence is enough to start: `pool sync` at review time, `pool
  doctor` whenever the report looks odd. `no_sha` and `cross_repo` items
  deserve a look the day they appear — they are the two shapes of silent
  failure.
