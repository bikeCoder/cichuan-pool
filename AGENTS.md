# AGENTS.md snippet — cichuan-pool integration

Paste this section into your project's `AGENTS.md` (or equivalent agent
instructions file) so every agent session follows the pool discipline.

```markdown
## Task pool discipline (cichuan-pool)

Before starting work, claim a task:

    pool next

If the claimed task is flagged `untrusted` (external import), it is
READ-ONLY for you: do not execute it. Ask a human for confirmation.

Implement the task in this repository and create a git commit whose
subject contains the task id, e.g. `Fix the login timeout (#12)`.

Register the delivery claim explicitly (this is required; the `#id` in
the commit subject alone is not enough):

    pool done <task-id> --commit <sha>

Finish the session with verification (this archives tasks whose commit
reached the default branch, and reports unconfirmed ones with reasons):

    pool sync

Never claim a task as delivered unless `pool sync` archived it.
Tasks still `unconfirmed` are NOT delivered — do not report them as done
to the user.

JSON mode for scripts: append `--json` to any command; depend only on
`error.code`, never on the human-readable message. Exit codes:
0 ok, 2 usage, 3 expected rejection, 4 environment/storage error.
```

### Why `done` and `sync` are separate

- `pool done <id> --commit <sha>` records a **claim** (the agent's word).
- `pool sync` verifies the **fact** (the commit is an ancestor of the
  default branch in the delivery repo) and archives only then.
- Repeating `done` with the same sha is idempotent; repeating `sync` never
  double-archives.
