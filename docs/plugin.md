# Plugin reference

Controls for the [Hierarchy of Defect Controls](hierarchy-of-defect-controls.md), each labelled at the rung it actually occupies. v0.5.1 is the release the round-5 adversarial review passed, plus its should-fix items. v0.6.0 added indicators, which are not controls and change no hook decision; the round-6 review passed it, and v0.6.1 is its should-fix items. Changes are listed at the end.

| Component | Rung | What it does |
|---|---|---|
| Gate (`hdc_hooks.py gate`, with `success` bookkeeping) | **Engineer, narrow** | Denies a call identical to one that has already failed twice *with the same error* when nothing has changed since the last failure. Scope: identical failing Bash and MCP retries. Not Edit rejections, not piped commands. The deny message's request to name a rung is Administer. |
| No-op in-place edit detector | **Engineer** for the identical-retry loop; **Administer** for the silent no-op itself | A simple `sed -i` or `perl -pi` that reports success while leaving its operand files byte-identical is recorded as a failure, so the gate blocks an identical retry. No git needed. `git apply` and `patch` are excluded on purpose: a repeated patch exits non-zero, so the failure path already covers it, and a patch-target parser produced false reports in three consecutive reviews. The model is also told, but acting on that is still up to the model. |
| Reminder (`hdc_hooks.py failure`) | **Administer** | Counts identical failure signatures outside the model and, on the second, injects a factual reminder as `additionalContext`. Counting outside the model and surviving compaction make it a better Administer control, not an Engineer one. |
| Reset (`hdc_hooks.py reset` on `UserPromptSubmit`) | support | A new user message clears gate counts. Reminder counts are kept. |
| `skills/hierarchy-of-defect-controls/SKILL.md` | **Administer** | The rules. Weaker than a project `CLAUDE.md`, since it loads only when the model matches it. |
| `scripts/hdc_report.py` | indicator, not a control | Read-only report over Claude Code transcripts: Tier 3 demands on the controls (denies, reminders, no-ops) grouped into episodes, exposure in tool calls, and the gate's cost in user messages. Not a hook; nothing it computes reaches the model. See [indicators](indicators.md). |
| Tier 4 log (`HDC_EVENTS`) | indicator, not a control | Opt-in. A hook exception that would otherwise be swallowed silently, or a corrupt state file, appends one record. Off by default; refuses symlinks and non-regular files. |

### What each control's indicators can show

Paired as in HSE dual assurance: how often the control is called on, and whether it failed when it was.

| Control | Demand (Tier 3) | Failure | Cost |
|---|---|---|---|
| Gate | denies | a loop that got past it by trivial variation: not measured | denies cleared by a user turn |
| Reminder | reminders | the loop went on to a deny anyway: episode depth | response length: not measured |
| No-op detector | no-op detections | an undetected no-op (compound command, patch): not measured | none observed |
| The hooks themselves | Tier 4 records | silent degradation that never raises: the captured-fixture test suite, not an indicator | none |

There is no Stop hook. An earlier version had a prompt hook that blocked when Claude acknowledged a repeat without naming a rung; it gated on disclosure, which prices honesty, and graded prose rather than substance. Do not re-add it.

Plugins do not load a `CLAUDE.md`, so the rules ship as a skill. To have them in every session, copy `CLAUDE.md` (in this directory) into your project.

## Install

    tar xzf hierarchy-of-defect-controls.tgz -C ~/.claude/skills

Loads on the next session as `hierarchy-of-defect-controls@skills-dir`. Or for one session: `claude --plugin-dir /path/to/hierarchy-of-defect-controls`. Hook changes need `/reload-plugins` or a restart. Requires `python3`; `git` for working-tree fingerprinting (edit-tool counter without it). Locking uses `fcntl`, so concurrent-write safety is POSIX only.

## Test

    python3 test/run_tests.py

74 tests. The first 47 simulate a tool call the way Claude Code does (gate, then the real command, then success or failure), covering the retest checklists from review rounds 2 through 4 where a live session is not required: reopening by Edit-tool write to a gitignored file, by `git checkout` on a clean tree, by external edits; the no-op detector on clean and dirty files, on gitignored and out-of-repo files, on compound commands, on read-only perl switches; every patch shape asserted never-flagged; signature collisions (pytest banner, output-less commands, hex and UUID ids); unborn `HEAD`; no git spawned for an unarmed `Read`; 13-way concurrency inside a git repo; and a direct check that the fingerprint never rewrites `.git/index`. The 0.6.0 tests run the report against a captured transcript excerpt and against the hooks' current messages (so the parser cannot drift from the text it parses), and check that the Tier 4 log is off by default, records a swallowed exception without command text, refuses a FIFO without blocking, and stays line-whole under 13 concurrent writers. The 0.6.1 tests are the round-6 regressions, each mutation-checked: a signature containing `")`, one record per corrupt state file, symlinks, a FIFO with a reader, no file opened anywhere when the log is off, and `traceback` kept off the hot path.

Payloads are built from `test/fixtures/*.json`, one per event, captured from a real Claude Code 2.1.270 session and sanitised (see `test/fixtures/README.md`). Re-capture after a Claude Code upgrade.

## How the gate decides

    deny  iff  identical call  AND  same error signature  AND  failed >= 2  AND  marker unchanged since last failure

"Identical call" is the tool name plus its input hashed exactly, ignoring only `description`. The marker has three parts, any of which reopens the gate:

- working-tree fingerprint: `git status` (untracked files by name, mtime, size) plus the plumbing diffs `git diff-files -p` and `git diff-index -p --cached HEAD`, all under `GIT_OPTIONAL_LOCKS=0`. Porcelain `git diff` would rewrite the index and take `index.lock`; this combination never does (0/400 concurrent commits failed in review).
- `HEAD`: so `checkout`, `pull`, `reset`, `stash pop` count as changes even on a clean tree.
- edit epoch: bumped by a successful `Edit`/`Write`/`MultiEdit`/`NotebookEdit`, so writes to gitignored or out-of-repo files count.

A new user message resets counts. A trailing shell comment is a different call; no hash can close that, and the deny message no longer suggests it.

The fingerprint is computed only when a decision needs it, outside the state lock. An unarmed `Read` spawns no git process.

## Tuning

- `THRESHOLD` (default 2): identical failures before the reminder fires and the gate arms.
- `EDIT_TOOLS`: which successful tools bump the edit epoch. Add edit-shaped MCP tools if you rely on the epoch (non-git directories).
- `GIT_TIMEOUT` (3 s per call): on a very large repo, raise it or accept the epoch-only fallback.
- To make the gate ask the user instead of denying, change `permissionDecision` to `"ask"`.

## Known gaps

- An `Edit` whose `old_string` is not found is rejected by validation before any hook fires.
- A non-zero exit hidden by a pipe (`pytest | tail`) or interpreted as non-error (`grep` with no match) arrives as `PostToolUse`, not a failure.
- A wrong answer with exit code 0 is invisible, except for the simple in-place edit case.
- Environment changes made through Bash (`pip install`, `docker start`, `export`) change none of the three marker parts. The escape is a new user message. In `-p` and inside subagents there is no user message; the escape there is a real input change.
- In-place edit detection covers `sed -i` and `perl -pi` only, and skips compound commands (unquoted `&&`, `||`, `;`, `|`, `&`, newlines) and invocations whose operands cannot be resolved to existing files. An empty patch applied with `--allow-empty` is a successful no-op nothing here detects.
- Hooks force the pause; they cannot force a good fix.
- Cowork: an open report says plugin hooks don't fire there.

Release history is in [CHANGELOG.md](../CHANGELOG.md).
