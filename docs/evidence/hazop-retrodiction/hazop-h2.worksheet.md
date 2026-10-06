# HAZOP worksheet: hierarchy-of-defect-controls plugin v0.1.0

Desk study, IEC 61882 adapted to software (CHAZOP / Def Stan 00-58 style). Subject: the read-only copy at
`scratchpad/hazop/subject/hierarchy-of-defect-controls/` (8 files: `.claude-plugin/plugin.json`, `hooks/hooks.json`,
`scripts/hdc_hooks.py`, `test/run_tests.sh`, `README.md`, `docs/CLAUDE.md`, `docs/hierarchy-of-defect-controls.md`,
`skills/hierarchy-of-defect-controls/SKILL.md`). File:line references below are to those files. Environment facts
come from Claude Code's public hooks and plugin documentation (code.claude.com/docs/en/hooks, plugins/loading,
plugins/components, plugins/manifest-reference), consulted 2026-10-06.

Team viewpoints applied to every node: (R) hook runtime and payload format, (C) concurrency and filesystem,
(G) git and other out-of-band file changes, (A) the constrained agent, including one that routes around the control,
(U) the human user, (F) the framework the docs claim to apply (do the labels and claims hold?).

Guide words: NO/NOT, MORE, LESS, AS WELL AS, PART OF, REVERSE, OTHER THAN, EARLY, LATE, BEFORE, AFTER.
Each row: deviation, cause (evidence), consequence, existing safeguard, recommendation, cross-reference to
`findings.json` (F-ids) where the deviation has a real consequence. Rows marked "not meaningful" record coverage.

Environment facts relied on (from the public docs):

- Every hook payload carries `session_id`, `cwd`, `hook_event_name`; `scratchpad_dir` is present only on Claude Code
  v2.1.257+ and only when the session has a scratchpad and the temp directory is available.
- `PostToolUseFailure` fires for Bash non-zero exits, tool execution errors, timeouts and interrupts, with fields
  `tool_name`, `tool_input`, `tool_use_id`, `error`, `is_interrupt`. `PostToolUse` fires on success (Bash exit 0).
- Hooks from plugins run inside subagents; the subagent payload carries the parent's `session_id` plus `agent_id`,
  `agent_type`. All matching hooks run in parallel. A timed-out hook produces no decision. Exit 0 with JSON on
  stdout is parsed; non-zero exit other than 2 is a non-blocking error (action proceeds).
- `PreToolUse` `permissionDecision: "deny"` blocks the call and shows `permissionDecisionReason` to Claude.
- A plugin directory with `.claude-plugin/plugin.json` saved under `~/.claude/skills/` loads as `<name>@skills-dir`,
  in place, including its hooks. `args` (exec form) is documented; `${CLAUDE_PLUGIN_ROOT}` resolves in `args`.
- A `CLAUDE.md` at the plugin root is not loaded as context (plugins ship rules as skills).

---

## Node 1: Hook wiring and manifest (`hooks/hooks.json`, `.claude-plugin/plugin.json`, install path)

**Design intent.** Register three command hooks, one per event, all tools (no matcher), each invoking
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/hdc_hooks.py <mode>` with a 10 s timeout (hooks.json:4-40). Manifest
declares name, version 0.1.0, description, keywords (plugin.json:1-6). README:16-20 gives the install path
(`tar xzf ... -C ~/.claude/skills`, or `--plugin-dir`), and says only `python3` on PATH is required.

**Parameters.** Inputs: event names, matcher (absent = all tools), command/args, timeout (seconds), env
(`CLAUDE_PLUGIN_ROOT`, PATH). Outputs: a spawned process per event per tool call. Environment: Claude Code version
(exec-form `args`, `scratchpad_dir`), OS (`python3` name), Cowork/claude.ai.

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 1.1 | hook process | NO | Hook never runs (python3 absent from Claude Code's PATH, pyenv shim only in interactive shell, Windows has `python` not `python3`) | hooks.json:9 exec form `"command": "python3"`; README:20 "Requires python3 on PATH" | Non-blocking hook error; all three controls silently absent (fail-open). The user sees nothing in normal mode. | README:28 manual check ("run `false` twice") | Ship a SessionStart self-test that writes a visible system message when the hook cannot run; or `#!/usr/bin/env python3` with a resolver that tries `python` | F11 |
| 1.2 | hook process | PART OF | Only some events wired (e.g. user copies the `PreToolUse` block into settings and forgets `PostToolUse`) | hooks.json has three independent blocks; nothing checks they are all present | Gate never reopens (no epoch bump) or never arms (no failure counting) | None | Document that the three hooks are one unit; consider one `SessionStart` health check that lists the modes seen | - |
| 1.3 | matcher | MORE | All tools are hooked, including Read, Grep, Glob, Agent, Skill, MCP, WebFetch | hooks.json: no `matcher` on any block | Three python processes per tool call (latency); Read/Grep/WebFetch failures are counted and gated like Bash (see 8.9) | 10 s timeout | Acceptable by design; note the cost in README | - |
| 1.4 | timeout | LESS | 10 s too short under load (cold filesystem, slow python startup, large state file) | hooks.json:11,23,35 | Timed-out hook produces no decision: a `success` timeout loses an epoch bump (gate stays shut after a real edit); a `failure` timeout loses a count | None | Keep state small (see 3.6); the 10 s margin is generous for the normal case | F7 |
| 1.5 | `args` | NOT (older runtime) | Runtime that ignores exec-form `args` runs bare `python3` with the payload on stdin | hooks.json:10,22,34; docs give no minimum version for `args` | `python3` would try to execute JSON as a script and exit 1: non-blocking error, fail-open | None | Use shell form with quoted `${CLAUDE_PLUGIN_ROOT}` for compatibility, or state the minimum Claude Code version | F11 |
| 1.6 | `scratchpad_dir` | NO (older runtime) | Payload lacks `scratchpad_dir` (< v2.1.257, or no temp dir) | hdc_hooks.py:108 falls back to `tempfile.gettempdir()` | Works, but state lands in shared `/tmp`, never cleaned, world-readable by default (contains command lines via `desc`) | `session_id` sanitised (hdc_hooks.py:110) | Prefer `CLAUDE_PLUGIN_DATA`/a per-user dir with 0600; delete on `SessionEnd` | F17 |
| 1.7 | manifest description | OTHER THAN | Manifest advertises "a fresh-context reviewer at Stop"; no Stop hook exists and README:12 says not to add one | plugin.json:4 vs hooks.json (no Stop) and README:12 | Users of `/plugin` see a control that does not exist; trust and audit confusion | None | Fix description; include the gate | F12 |
| 1.8 | install path | OTHER THAN | User follows the skill-style install but the archive layout differs (SKILL.md nested under `skills/`) | README:18; docs: a `.claude-plugin/plugin.json` directory under `~/.claude/skills/` loads as a plugin | Documented path works, verified against docs; not meaningful | - | - | - |
| 1.9 | install path | AS WELL AS | Same plugin loaded twice (`--plugin-dir` and `@skills-dir`) | Docs: `--plugin-dir` shadows the skills-dir copy; only one loads | Not meaningful | - | - | - |
| 1.10 | hook reload | LATE | Hook edits need `/reload-plugins`; skill edits are live | README:20 | Not meaningful (documented) | - | - | - |
| 1.11 | platform | OTHER THAN | Cowork / claude.ai | README:48 flags an open report | Controls absent there; documented as unverified | README:48 | Verify and state | - |

## Node 2: Entry point and dispatch (`main`, `MODES`, fail-open policy)

**Design intent.** Parse `argv[1]` as the mode, read JSON from stdin, dispatch; any exception exits 0 silently so
a bug "can never break a session" (hdc_hooks.py:25-28, 257-268). An `edit` alias of `success` exists but is unused
(hdc_hooks.py:17, 252).

**Parameters.** Inputs: argv mode, stdin JSON (dict expected). Outputs: stdout JSON or nothing; exit code always 0.

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 2.1 | exit code | NO (never non-zero) | Every error, including a real bug or an unreadable state dir, exits 0 with no output | hdc_hooks.py:266-268 | All failures are silent always-pass; the plugin's own rule (docs/CLAUDE.md:19) calls this "worse than no check" | README:26 test script; docstring admits it (hdc_hooks.py:25-28) | Write a one-line diagnostic to stderr on exception (stderr on exit 0 is logged, not shown to Claude) and expose a health signal; or exit 1 with stderr so `--debug` shows it | F11 |
| 2.2 | payload | OTHER THAN | Payload is a JSON array or scalar | hdc_hooks.py:264 `isinstance(payload, dict)` guard | Silently ignored; fine | guard | - | - |
| 2.3 | payload | PART OF | Truncated/invalid JSON on stdin | hdc_hooks.py:263 raises, swallowed | Silent; fine | try/except | - | - |
| 2.4 | mode | OTHER THAN | Unknown mode string | hdc_hooks.py:260-262 | Silent; tested (run_tests.sh:45) | test | - | - |
| 2.5 | mode | AS WELL AS | `edit` alias is wired nowhere | hdc_hooks.py:17, 252; hooks.json uses `success` | Dead code; harmless | - | Remove or use | - |
| 2.6 | stdout | MORE | Exception after `emit` partially wrote? `emit` is last in both paths | hdc_hooks.py:139, 196-197, 240 | Not meaningful | - | - | - |

## Node 3: State file and its lifecycle (`state_path`, `load_state`, `save_state`)

**Design intent.** One JSON file per session at `<scratchpad_dir or tempdir>/hdc-state-<session_id>.json`, holding
`edit_epoch`, `signatures`, `calls` (hdc_hooks.py:107-135). Read-modify-write on every event; atomic rename via a
fixed `.tmp` sibling. Survives compaction because `session_id` is unchanged (README:8).

**Parameters.** Inputs: `scratchpad_dir`, `session_id`. State: three maps, unbounded. Timing: created on first
failure/success event; never deleted. Concurrency: no lock. Environment: scratchpad dir existence, permissions,
`--resume`, `--fork-session`, subagents (same `session_id`).

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 3.1 | state dir | NO | `scratchpad_dir` is reported but the directory does not yet exist (created lazily) or is not writable | hdc_hooks.py:108 uses the path as-is; no `os.makedirs`; hdc_hooks.py:134 swallows `OSError` | Every save fails silently; counts never persist; gate never arms (always-pass) | None | `os.makedirs(base, exist_ok=True)`; stderr diagnostic | F10 |
| 3.2 | state file | PART OF / OTHER THAN | Corrupt or partial JSON (concurrent writer, disk full) | hdc_hooks.py:118-121 resets to `{}` | Whole session's counts and epoch silently reset to zero; gate reopens | atomic `os.replace` for single writer | Lock the file (`fcntl.flock`) or write to a unique temp name (`tempfile.mkstemp` in the same dir) | F7 |
| 3.3 | writers | MORE (concurrent) | Two hook processes (parallel tool batch, or parent + subagent) read, modify and write the same file; both use the same `path + ".tmp"` | hdc_hooks.py:130-133; docs: all matching hooks run in parallel, subagent hooks share `session_id` | Lost update: a failure count or an epoch bump disappears; or interleaved writes to the shared `.tmp` leave corrupt JSON (3.2) | None | File lock; unique temp names; or key state per `tool_use_id` batches | F7 |
| 3.4 | session scope | MORE (shared across agents) | Parent and all subagents share one state file | hdc_hooks.py:109 keys on `session_id` only; `agent_id` ignored | Three parallel subagents each running `pytest` once pool to count 3 and the third is denied; a subagent's Edit reopens the parent's gate; the parent is denied for failures it never saw and told "has failed 2 times in this session" | None | Include `agent_id` in the state key (or in the call key), or document the pooling as intended | F6 |
| 3.5 | session scope | AFTER (resume) | `--resume` keeps `session_id` and scratchpad; counts and epoch persist across days; the user may have edited files meanwhile | hdc_hooks.py:107-111; docs: scratchpad is per session | A command that failed twice last week is denied on the first try today with "no file has been edited since the last failure", which is untrue | None | Store a timestamp and expire entries; or reset on `SessionStart` with `source: resume` | F18 |
| 3.6 | size | MORE | Maps grow without bound (every distinct failing call and signature for the session); a subagent loop can add thousands | hdc_hooks.py:123-124, 177, 186 | Each hook loads/dumps the whole file; eventually slow; 10 s timeout then drops decisions (1.4) | None | Cap entries; evict LRU | F7 |
| 3.7 | lifecycle | NO (never deleted) | No `SessionEnd` cleanup; `/tmp` fallback accumulates | hdc_hooks.py (no delete path) | Clutter; on shared hosts, command lines (`desc`) readable by others | scratchpad is session-scoped on new versions | Add `SessionEnd` cleanup; 0600 perms | F17 |
| 3.8 | `session_id` | NO | Missing field | hdc_hooks.py:109 `"unknown"` | All sessions without an id share one file; only on a schema change | - | - | - |
| 3.9 | TMPDIR | OTHER THAN | Hook environment `TMPDIR` differs from the one the test used | hdc_hooks.py:108; run_tests.sh:7 | Not meaningful in production (keyed by session) | - | - | - |
| 3.10 | compaction | BEFORE/AFTER | State is independent of context; survives compaction | README:8 | Intended; holds | - | - | - |
| 3.11 | fork | OTHER THAN | `--fork-session` gets a new id; state lost | docs: fork is a new session | Minor; intended | - | - | - |

## Node 4: Call fingerprint ("identical call", `canonical_call`, `IGNORED_INPUT_FIELDS`)

**Design intent.** Key = sha1(tool name + canonical JSON of `tool_input`), with `description`, `timeout`,
`run_in_background` dropped and whitespace in strings collapsed, so retries that differ only in intent or plumbing
match (hdc_hooks.py:61-82; README:34).

**Parameters.** Inputs: `tool_name`, `tool_input` (any JSON). Output: 16-hex key. Used by failure (count), success
(pop), gate (lookup).

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 4.1 | `timeout` | NOT (ignored) | Call failed twice by timing out; agent retries with a larger `timeout`, the correct remedy | hdc_hooks.py:64 drops `timeout`; docs: timeouts fire `PostToolUseFailure` | Treated as "unchanged"; denied; the deny text says to change the input, which the agent already did. Running in background (`run_in_background`) is likewise ignored | None | Keep `timeout`/`run_in_background` in the key, or treat a timeout error (`is_interrupt`/error text) as not counting | F1 |
| 4.2 | `tool_input` | OTHER THAN (trivially varied) | Agent adds `-q`, `./`, `2>&1`, `; true`, `cd . &&` or a trailing comment | hdc_hooks.py:67-82 exact-content key; README:34 calls this a "deliberate escape hatch"; deny text hdc_hooks.py:236-238 says "vary the call" | New key, count 0; the loop continues with cosmetic variation. The control teaches its own bypass. CLAUDE.md:29 "cannot be talked past, only edited past" overstates it | README:34 asks the agent to "say so" (Administer) | Normalise Bash commands further (strip comments, `2>&1`, trailing `; true`) and count near-duplicates; at least log variants for the user | F5, F20 |
| 4.3 | whitespace | LESS | Collapsing whitespace inside quoted strings changes meaning (`echo "a  b"`) but only for keying | hdc_hooks.py:75 | Two genuinely different commands keyed together: very rare | - | - | - |
| 4.4 | `tool_name` | NO | Field missing/renamed | hdc_hooks.py:167, 201, 217 default `"unknown"`, `tool_input` `{}` | Every call collapses to one key: after any two failures, every tool call including Edit is denied until the user disables the plugin (lock-out, the opposite of fail-open) | None | If `tool_name` is absent, return without acting | F16 |
| 4.5 | `tool_input` | OTHER THAN (non-dict) | String or list input (some MCP tools) | hdc_hooks.py:71-80 handles | Not meaningful | - | - | - |
| 4.6 | key | AS WELL AS | Different tools, same input | tool name is in the hash (hdc_hooks.py:82) | Not meaningful | - | - | - |
| 4.7 | key | PART OF | 16 hex chars of sha1 | hdc_hooks.py:82 | Collision negligible | - | - | - |
| 4.8 | Edit inputs | MORE | Edit call key includes `old_string`/`new_string`; identical failing Edit (string not found) twice then denied | by design | Intended: the agent must re-read and change the strings | - | - | - |

## Node 5: Error signature (`extract_error`, `normalise_error`)

**Design intent.** Reduce the failure text to a coarse, stable first-line signature: lower-case, strip pytest
`E` prefix, mask hex, timestamps, `/tmp` paths, line numbers, all integers; cap at 160 chars (hdc_hooks.py:45-58,
85-94). README:40: "Coarse on purpose."

**Parameters.** Inputs: `error` (string), fallbacks `tool_response`/`result`/`output` with sub-keys. Output:
signature string; empty means "do not count".

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 5.1 | first line | PART OF | Only the first line is kept; Bash failure text for a test runner begins with a generic banner (`exit code 1: ===== test session starts =====`) or the command's first stdout line | hdc_hooks.py:49 `splitlines()[0]`; docs example error begins `exit code 1: ...` | Every pytest/npm-test failure in the session shares one signature regardless of which test or why; reminder fires on the 2nd test failure of any kind and escalates forever (see 6.4) | - | Hash the last N lines or the first line that matches an error pattern (`Error|error:|FAILED|Traceback`) | F9 |
| 5.2 | digits | MORE (over-masked) | All integers become `<n>`: `exit code 1` and `exit code 2`, `3 failed` and `30 failed` match | hdc_hooks.py:56 | Adds to 5.1 collisions; intended coarseness | README:40 | - | F9 |
| 5.3 | `error` | NO | Empty error (a command that fails silently, e.g. `false`), or renamed field | hdc_hooks.py:47-48, 85-94 return "" | No signature counted: reminder never fires; the gate still counts the call. README:26 is right that a rename is silent for the reminder | gate path independent | - | - |
| 5.4 | `error` | OTHER THAN (interrupt) | User pressed Escape; `is_interrupt: true`; error text like "interrupted" | hdc_hooks.py never reads `is_interrupt` | Interrupts are counted both as signatures and as call failures; after two interrupts the reminder says the tool "failed 2 times with the same signature" and the third run is denied | None | Return early when `is_interrupt` is true | F2 |
| 5.5 | `error` | OTHER THAN (attacker text) | The first 160 chars of error output are echoed verbatim into `additionalContext`; a failing test or fetched page can place instructions there | hdc_hooks.py:149, 191; the code comment at 145-146 recognises the injection channel yet echoes the text | A repository under test can inject text into a system-reminder-channel message; bounded to 160 lower-cased chars | lower-casing, 160 cap | Do not echo the signature; show the hash and tool name, or escape/quote clearly | F14 |
| 5.6 | fallback keys | AS WELL AS | On `PostToolUseFailure`, `tool_response` is not a documented field; the fallback chain is for schema drift | hdc_hooks.py:86 | Harmless | - | - | - |
| 5.7 | signature | LESS (too narrow) | Same root cause with different first lines (flaky ordering, different file paths outside `/tmp`) | hdc_hooks.py:53 masks only `/tmp/` paths | Reminder under-fires for repeats whose first line carries a project path with a changing name; the gate (exact call) still works | - | Mask absolute paths generally | - |

## Node 6: `failure` mode (PostToolUseFailure handler)

**Design intent.** On every tool failure: increment the exact-call count and stamp it with the current
`edit_epoch`; increment the signature count; on count >= THRESHOLD emit the reminder as `additionalContext`
(hdc_hooks.py:166-197). Signature counts are never decremented or cleared.

**Parameters.** Inputs: payload (Node 4, Node 5), state. Outputs: updated state; optional reminder. Timing: after
the tool ran. Concurrency: Node 3.

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 6.1 | event | NO | Failure not reported as failure: the command's exit status is masked by a pipe (`pytest ... 2>&1 \| tail -50`), `\|\| true`, `; echo done`, or a wrapper script that exits 0 | docs: `PostToolUseFailure` fires on non-zero exit only; hdc_hooks.py:200-213 then treats it as success and pops the call key | The most common way agents run tests is invisible to both controls; the success path actively erases any earlier count for that key. README:45 names "wrong answer with exit code 0" in general but not this routine case | None | Heuristically inspect `tool_response.output` for failure markers in `success` mode; warn in README that piping to `tail`/`head` defeats the plugin unless `set -o pipefail` | F3 |
| 6.2 | event | NO (background) | `run_in_background: true` runs report success at launch; the later failure fires no `PostToolUseFailure` | docs semantics; hdc_hooks.py has no handling | Background re-runs never count | None | Document; treat background launches as neither success nor failure (do not pop) | F3 |
| 6.3 | count | MORE | Interrupts and timeouts counted as failures of the agent's own making | hdc_hooks.py:175 unconditional increment | See 5.4, 4.1 | None | Skip `is_interrupt`; treat timeout distinctly | F1, F2 |
| 6.4 | signature count | MORE (never cleared) | Signature counts are only ever incremented; `success` clears call keys but not signatures (hdc_hooks.py:207 vs 184-186) | hdc_hooks.py:184-186 | After a genuine fix earlier in the session, the next failure with a colliding signature prints "This is occurrence N; the previous remedy was too low on the ladder": a false accusation that grows all session. Combined with 5.1 this becomes "every test failure" | None | Reset a signature when a call with that signature later succeeds; or decay by epoch | F8 |
| 6.5 | reminder threshold | EARLY | Reminder and gate both act at the second failure | THRESHOLD=2 (hdc_hooks.py:38) | On the second failure the agent gets the reminder and is simultaneously gated on the identical call; consistent with README:7-8 | - | - | - |
| 6.6 | epoch stamp | REVERSE | A failure stamps the current epoch; a later edit changes `edit_epoch`, not the stamp | hdc_hooks.py:176, 226 | Correct direction; holds | - | - | - |
| 6.7 | denied calls | AS WELL AS | If a hook-denied call also produced a failure event, each denial would increment the count | Not documented either way; hdc_hooks.py:175 would count it | Inflated "has failed N times" text; no functional change | - | Verify against a real session (README:28) | - |
| 6.8 | emit | LATE | Save happens before emit; an emit failure cannot lose state | hdc_hooks.py:195-197 | Not meaningful | - | - | - |
| 6.9 | expected failures | OTHER THAN | Commands whose non-zero exit is the normal signal: `grep -q`, `test -f`, `git diff --exit-code`, `diff`, `curl` health polling, `git commit` with nothing staged | all count equally | Two polls fail (service not up yet); third poll denied with no edit possible; the deny text teaches variation | README:46 accepts the false-positive surface | Allowlist by pattern or let the user tune via `userConfig`; treat `is_interrupt`/polling patterns specially | F15 |

## Node 7: `success` mode and the "has anything changed" marker (`edit_epoch`)

**Design intent.** A successful call clears its own retry count; a successful Edit/Write/MultiEdit/NotebookEdit
increments `edit_epoch`, which reopens the gate for every call (hdc_hooks.py:200-213; README:9).

**Parameters.** Inputs: `tool_name`, `tool_input`. State: `edit_epoch` (monotonic integer), `calls`. Timing: after
the tool ran. Environment: git, user's editor, Bash-driven file changes, MCP edit tools.

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 7.1 | edit detection | NO | Files changed by means other than the four tools: `sed -i`, `git checkout/stash/pull/rebase`, `npm install`, `pip install`, `make`, generated files, a background process writing output, an MCP editing tool, the user's own editor, a formatter run by a failing pre-commit hook | hdc_hooks.py:40 `EDIT_TOOLS` fixed set; hdc_hooks.py:210 | Gate stays shut after a real change; deny text says "no file has been edited since the last failure", which is false; the user who edited in their IDE and asked for a rerun is refused; the agent is steered to vary the command | README:39 says to add MCP tools by hand | Add a fingerprint of the working tree (e.g. `git status --porcelain` + mtimes, or `git diff \| sha1`) taken at failure time and compared at gate time, instead of counting tool calls | F4 |
| 7.2 | edit detection | MORE (too permissive) | Any successful edit of any file, anywhere, reopens the gate for every gated call: a one-character comment change, a Write to `/tmp/x`, or appending `repeat: ...` to `NOTES.md` as docs/CLAUDE.md:31 instructs | hdc_hooks.py:210-211 global epoch; docs/CLAUDE.md:31 | The plugin's own procedure (record the repeat in NOTES.md) is an Edit that unlocks the identical retry; an agent that wants through makes any trivial edit. CLAUDE.md:29 "only edited past" is literally true and that is the weakness | None | Tie the epoch to the files the failing call plausibly depends on (cwd/project tree), exclude notes files, or require that the edited file be inside the project and not a notes file | F5 |
| 7.3 | success pop | REVERSE | A success with the same key clears the count, which is right, but a masked success (6.1) also clears | hdc_hooks.py:207 | See F3 | - | - | F3 |
| 7.4 | edit success | OTHER THAN | A Write that rewrites identical content, or an Edit with `replace_all` that matched (tool reports success) | counted as edit | No-op edits reopen the gate; same as 7.2 | - | - | F5 |
| 7.5 | epoch | LATE | The `PostToolUse` hook for the Edit times out or races (Node 3) | 1.4, 3.3 | Bump lost; gate stays shut; agent makes another edit to get through (training the bypass) | - | File lock | F7 |
| 7.6 | ordering | BEFORE | Edit and the retry issued in the same parallel batch; the retry's `PreToolUse` may run before the Edit's `PostToolUse` | docs: hooks in a batch run in parallel | Spurious deny; low likelihood (Claude Code serialises non-read-only tools) | - | - | F7 |
| 7.7 | EDIT_TOOLS | OTHER THAN (renamed tool) | A future rename of Edit tools, or an MCP-based editor | hdc_hooks.py:40 | Epoch never bumps; gate becomes permanently shut after two failures until the user intervenes | README:39 | Health test; tree fingerprint (7.1) | F4 |
| 7.8 | failed edit | AS WELL AS | A failed Edit (old_string not found) correctly does not bump the epoch | failure path | Holds | - | - | - |

## Node 8: `gate` mode (PreToolUse handler)

**Design intent.** Deny iff the exact call has failed >= THRESHOLD times and its last failure's epoch equals the
current `edit_epoch` (hdc_hooks.py:216-246; README:30-34). Labelled "Engineer" (README:7).

**Parameters.** Inputs: payload (Node 4), state. Output: deny JSON with reason, or nothing. Timing: before the tool
runs. Environment: permission modes, user intent, subagents.

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 8.1 | decision | NO (fail-open) | Any exception, missing state, timeout, missing python3 | hdc_hooks.py:266; Node 1, 2, 3 | Always-pass with no indication | README:26-28 (manual) | Health signal | F11 |
| 8.2 | decision | MORE (false deny) | Count reached via interrupts/timeouts/subagents/resume; epoch not bumped because the change happened outside EDIT_TOOLS | 4.1, 5.4, 3.4, 3.5, 7.1 | Legitimate work blocked; user's explicit instruction refused; message asserts an untruth ("no file has been edited") | deny reason offers variation | See F1, F2, F4, F6, F18 | F1 F2 F4 F6 F18 |
| 8.3 | decision | LESS (false allow) | Count erased by masked success, lost by race, or reset by corruption; key changed by trivial variation; failures run in background | 6.1, 3.2, 3.3, 4.2, 6.2 | Loop continues unseen | - | See F3, F5, F7, F20 | F3 F5 F7 F20 |
| 8.4 | deny reason | AS WELL AS (instructs bypass) | Reason text tells the agent to "vary the call in a way that reflects that judgement" and to "say so to the user" | hdc_hooks.py:236-238; README:34 | An agent under pressure learns that a cosmetic variation unlocks the call; the "say so" is an Administer request layered on an Engineer label | - | Remove the bypass instruction; instead instruct: "make a change to the code or input, then retry the same call"; or use `ask` so the user decides | F20 |
| 8.5 | decision | OTHER THAN (`ask`) | README:41 suggests `ask` as a tuning | README:41 | Safer for the human-in-the-loop case; not default | - | Consider `ask` default in interactive sessions | - |
| 8.6 | epoch compare | REVERSE | `epoch != edit_epoch` reopens; a stale call entry from a wiped-and-regrown state could compare unequal and pass | 3.2 | Minor; covered by F7 | - | - | - |
| 8.7 | threshold | EARLY | Count from an earlier context (before many edits) plus one fresh failure makes count 3 and shuts the gate at once | hdc_hooks.py:224 count is cumulative | A call that failed twice at 9am, was fixed by edits, and fails once at 5pm is shut immediately; arguably intended ("already failed twice") but the message "failed 3 times ... no file edited since the last failure" is literally true yet misleading | - | Reset count on an epoch change, or show the last-failure epoch distance | F8 |
| 8.8 | scope | MORE (all tools) | Read/Glob/Grep/WebFetch/Agent/Skill are gated | hooks.json no matcher | Read of a file a background build is about to produce fails twice, then is denied until an Edit; WebFetch of a flaky URL likewise | README:46 | Restrict gate to Bash and MCP tools, or to tools with side effects | F15 |
| 8.9 | user intent | OTHER THAN | The user explicitly asks "run it again, I changed X in my editor" | 7.1 | Refusal of a direct user instruction, with a false statement | - | Tree fingerprint; `ask` | F4 |
| 8.10 | label | OTHER THAN | README:7 "Engineer ... it blocks; it does not remind"; CLAUDE.md:29 "cannot be talked past" | 4.2, 7.2, 8.4 | By the docs' own definition (CLAUDE.md:18-19) a control that is fail-open, trivially re-keyed, and reopened by any edit is weaker than its label; the reminder is honestly labelled Administer | README:46-47 acknowledge limits | Re-label as "Engineer gate with an Administer escape" and state the bypass surface | F13 |

## Node 9: Messages emitted to the agent (`reminder_text`, deny reason, `describe_call`)

**Design intent.** Factual, non-imperative text (hdc_hooks.py:145-146) carrying tool, count, signature, and the
ladder vocabulary; deny reason names the call and count (hdc_hooks.py:229-238).

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 9.1 | content | AS WELL AS (untrusted text) | Signature (160 chars of error) and `desc` (120 chars of command) are embedded in system-side context | hdc_hooks.py:149, 191, 230 | Injection channel from tool output; low but the file itself flags the concern | lower-case, caps | Omit raw text or fence it | F14 |
| 9.2 | content | OTHER THAN (wrong facts) | "failed N times" counts interrupts/timeouts/subagent runs; "no file has been edited" ignores non-tool edits; "occurrence N; previous remedy too low" after collisions | 5.4, 3.4, 7.1, 6.4 | Agent and user receive false statements from a control that claims to be factual; erodes trust, agent learns to ignore the reminder | - | Fix sources; soften wording ("no Edit/Write tool call has succeeded since") | F2 F4 F6 F8 |
| 9.3 | content | MORE (two counts) | Reminder count is per signature; deny count is per call; they differ and both say "failed N times in this session" | hdc_hooks.py:148, 230-231 | Confusing but not harmful | - | Name the basis of each count | - |
| 9.4 | content | AS WELL AS | Deny reason includes a bypass recipe | 8.4 | See F20 | - | - | F20 |
| 9.5 | rung claim | OTHER THAN | Reminder says resolving to be careful is "Protect-rung"; docs/CLAUDE.md:25 says it is "Administer with nothing written down"; SKILL.md:27 and hdc doc:86 say Protect | hdc_hooks.py:151; docs/CLAUDE.md:25; SKILL.md:27 | The plugin's own files classify the same remedy on two rungs; the framework's value is consistent labelling | - | Pick one and align all four texts | F13 |
| 9.6 | length | MORE | Under the 10,000-char cap | hdc_hooks.py:147-163 | Not meaningful | - | - | - |

## Node 10: Concurrency and subagents (cross-cutting)

**Design intent (implicit).** None stated; the code assumes one writer at a time and one agent per session.

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 10.1 | writers | MORE | Parallel tool batches and parallel subagents | 3.3 | Lost updates / corruption | None | Lock | F7 |
| 10.2 | agents | MORE | N subagents share counts and epoch | 3.4 | Cross-agent false deny/allow | None | Key by `agent_id` | F6 |
| 10.3 | ordering | BEFORE/AFTER | PreToolUse of call B before PostToolUse of call A in one batch | 7.6 | Spurious deny | - | - | F7 |
| 10.4 | Agent tool | AS WELL AS | The `Agent` launch itself is a tool call that can fail twice and be gated | hooks.json no matcher | Intended by the all-tools design | - | - | - |

## Node 11: Tests (`test/run_tests.sh`)

**Design intent.** Fifteen assertions walking a fake session; "run it after any Claude Code update ... a renamed
field fails as silent always-pass" (README:26).

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 11.1 | payloads | OTHER THAN (synthetic) | The test fabricates its own payloads (`error` as a bare pytest `E` line; Edit with `old_str`/`new_str`, which are not the real field names `old_string`/`new_string`; no `scratchpad_dir`, `tool_use_id`, `is_interrupt`) | run_tests.sh:17-26 | The suite can never detect a renamed Claude Code field: it tests the script against the script's own assumptions. README:26 claim is false; README:28 manual check is the only real-payload test and it covers the gate only | README:28 | Record real payloads (a `PostToolUseFailure` hook that tees stdin to a fixture) and replay them; assert on the documented field set | F19 |
| 11.2 | assertions | NO (vacuous) | Six "EMPTY" assertions (lines 28,29,30,36,44,45) pass when the script crashes, because every exception is swallowed to empty output | run_tests.sh:11-12; hdc_hooks.py:266 | A crash in `gate` before any failure is indistinguishable from "correctly silent" | later positive assertions catch most | Have the script print a diagnostic to stderr on exception and make the test fail on non-empty stderr | - |
| 11.3 | state path | PART OF | Tests exercise only the `tempfile.gettempdir()` fallback, never `scratchpad_dir` | run_tests.sh:7, 17 | 3.1 (missing dir) untested | - | Add a case with `scratchpad_dir` pointing at a non-existent dir | F10 |
| 11.4 | coverage | LESS | No test for: interrupts, timeout retried with larger timeout, subagent payloads (`agent_id`), concurrent writers, signature never clearing, Bash multi-line error text | run_tests.sh | The deviations in F1, F2, F6, F7, F8 are all untested | - | Add cases | - |
| 11.5 | count claim | OTHER THAN | README says fifteen; the script has fifteen `check` calls | run_tests.sh:28-45 | Holds; not meaningful | - | - | - |
| 11.6 | isolation | AS WELL AS | `TMPDIR` export plus `trap rm -rf` | run_tests.sh:7-8 | Fine | - | - | - |

## Node 12: Documentation and rules as procedure (`README.md`, `docs/CLAUDE.md`, `SKILL.md`, `docs/hierarchy-of-defect-controls.md`)

**Design intent.** State the design, label each component at the rung it "actually occupies" (README:3), give
rules the agent follows (SKILL.md; CLAUDE.md copied by the user), and procedures (NOTES.md `repeat:` lines,
`grep -c` threshold).

| # | Parameter | Guide word | Deviation | Cause / evidence | Consequence | Safeguard | Recommendation | Ref |
|---|---|---|---|---|---|---|---|---|
| 12.1 | claim | OTHER THAN | "cannot be talked past, only edited past" (CLAUDE.md:29) vs README:34 "a different flag is a different call" and the deny text's variation advice | CLAUDE.md:29; README:34; hdc_hooks.py:236-238 | The rules file given to the agent overstates the gate; the README contradicts it | - | Align | F13 |
| 12.2 | procedure | AS WELL AS (self-defeating) | CLAUDE.md:31 directs an Edit/Write to NOTES.md on noticing a repeat; that edit reopens the gate (7.2) | CLAUDE.md:31; hdc_hooks.py:210 | Following the rules unlocks the identical retry that the gate exists to stop | - | Exclude notes files from epoch bump, or fingerprint the tree | F5 |
| 12.3 | label | OTHER THAN | Manifest description names a Stop reviewer; README:12 says none exists | plugin.json:4 | Misleading metadata | - | Fix | F12 |
| 12.4 | rung consistency | OTHER THAN | "Resolve to be careful" is Protect (SKILL.md:27, hdc doc:86, reminder) and Administer (CLAUDE.md:25) | as cited | Internal inconsistency in the framework the plugin teaches | - | Align | F13 |
| 12.5 | own rules applied to itself | NOT | CLAUDE.md:7 lists "an assertion that the mechanism fired at all" as an Engineer control; CLAUDE.md:19 "a check that reads a field the payload does not contain fails as silent always-pass, which is worse than no check"; the plugin ships no mechanism-fired check and the test cannot detect a renamed field | hdc_hooks.py:25-28; run_tests.sh | The plugin fails its own standard | README:26-28 (Administer) | Health signal (SessionStart hook that performs a dry run and reports), real-payload fixtures | F19 F11 |
| 12.6 | README count | PART OF | README:45 "Both hooks" when three are wired | README:45 | Cosmetic | - | Fix wording | - |
| 12.7 | NOTES.md procedure | OTHER THAN | Threshold is a `grep -c` on `repeat:` lines; projects with no NOTES.md, or multiple collaborators' notes | CLAUDE.md:31 | Administer, acknowledged as such; not a defect | - | - | - |
| 12.8 | install docs | OTHER THAN | README:14 says plugins do not load a CLAUDE.md; docs confirm | README:14 | Holds | - | - | - |
| 12.9 | Known limits | PART OF | README:43-48 lists exit-0 wrong answers and narrowness but not: interrupts, timeouts, pipes, subagents, out-of-tool edits, any-edit reopening, resume persistence | README:43-48 | User cannot calibrate trust in the control | - | Extend Known limits with the findings here | F1-F8 |

---

Totals: 12 nodes; 95 worksheet rows (including rows recorded as not meaningful for coverage).
