# HAZOP worksheet: hierarchy-of-defect-controls plugin v0.1.0

Desk study, IEC 61882 adapted to software (CHAZOP / Def Stan 00-58 style). Subject: the read-only
copy under `scratchpad/hazop/subject/hierarchy-of-defect-controls/`. All file:line references are to
that copy. `H` = `scripts/hdc_hooks.py`, `W` = `hooks/hooks.json`, `M` = `.claude-plugin/plugin.json`,
`R` = `README.md`, `C` = `docs/CLAUDE.md`, `D` = `docs/hierarchy-of-defect-controls.md`,
`S` = `skills/hierarchy-of-defect-controls/SKILL.md`, `T` = `test/run_tests.sh`.

Environment facts used (from Claude Code's public hooks, plugin and subagent documentation, not from
the plugin):

- E1. `PostToolUseFailure` input carries `tool_name`, `tool_input`, `tool_use_id`, `tool_error`,
  `tool_output`, `tool_response` (an object: `{type, content:[{type,text}], is_error}`) and
  `is_interrupt`. It fires for tool errors (including Bash non-zero exit), tool timeouts, user
  `Ctrl+C` interrupts, and a user refusing a `PermissionRequest`. It does not fire when a
  `PreToolUse` hook denies or when the permission system blocks (the model sees a tool error result).
- E2. Common fields: `session_id`, `cwd`, `transcript_path`, `hook_event_name`, `permission_mode`,
  `scratchpad_dir` (optional; v2.1.257+; absent when unavailable), `agent_id`/`agent_type` inside
  subagents.
- E3. Subagent tool calls run the same plugin hooks and carry the parent's `session_id`.
  Background subagents run concurrently.
- E4. All matching hooks for an event run in parallel. In a parallel tool batch every call's
  `PreToolUse` fires before any executes; the post hooks of the batch run in parallel. For
  `run_in_background` Bash, `PostToolUse` fires asynchronously when the task completes.
- E5. Exit 0 + stdout JSON is honoured; timed-out hooks have output discarded and on `PreToolUse` the
  tool proceeds. A `command` hook with `args` runs in exec form (no shell), `${CLAUDE_PLUGIN_ROOT}`
  substituted in args. `additionalContext` is capped at 10,000 chars.
- E6. `session_id` is unchanged across `--resume`/`--continue`; `/clear` gives a new one.
- E7. A directory with `.claude-plugin/plugin.json` under `~/.claude/skills/` loads as
  `<name>@skills-dir`, hooks included (personal scope has no trust restrictions). Plugins never load a
  `CLAUDE.md`.
- E8. `PostToolUse` `additionalContext`/`decision` output and `PreToolUse`
  `permissionDecision: deny` + `permissionDecisionReason` work as the script assumes.

Guide words: NO/NOT, MORE, LESS, AS WELL AS, PART OF, REVERSE, OTHER THAN, EARLY, LATE, BEFORE, AFTER.
Rows marked "n/m" are combinations judged not meaningful, kept so coverage is visible.
Severity: H/M/L is the reviewer's judgement of consequence x credibility. "F#" links to
`findings.json`.

---

## Node 1: Hook wiring and manifest (`W`, `M`)

**Design intent.** Register one Python script in three modes on every tool call: `gate` on
`PreToolUse`, `success` on `PostToolUse`, `failure` on `PostToolUseFailure` (W:4-40). Runs via
`python3` in exec form with `${CLAUDE_PLUGIN_ROOT}` (W:9-10), 10 s timeout (W:11). Manifest
declares name/version/description (M:2-4). README says only `python3` on PATH is required (R:20).

**Parameters.** Inputs: hook event, payload on stdin, argv mode. Outputs: stdout JSON. State: none.
Timing: 2 Python process launches per tool call (gate + success/failure). Concurrency: parallel with
any other hook and with itself (E4). Environment: Claude Code version supporting `args` exec form and
plugin hooks; `python3` resolvable; plugin loaded from marketplace, `--plugin-dir`, or skills dir (E7).

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| NO | hook execution | Hooks never run | `python3` absent/misnamed (Windows `python`, macOS stub that triggers Xcode CLT prompt), plugin not enabled, `args` exec form unsupported on an older Claude Code so `python3` runs with no argv and reads the JSON payload as a script (W:9-10; H:259-262 returns 0 for empty mode) | Whole plugin is silent always-pass; nothing tells the user (R:20 names the dependency; H:25-28 admits the mode) | README manual check (R:28) only if the user remembers | Add a `SessionStart` self-test that writes a one-line `systemMessage` if the state dir or interpreter is unusable; pin a minimum Claude Code version in README | M (F17) |
| NO | matcher | No `matcher` on any event | Intentional "all tools" (W:5,17,29) | Gate and counters apply to Read, Grep, WebFetch, Agent, AskUserQuestion, MCP tools; see Node 5 OTHER THAN | None | Consider `matcher` or an allowlist of tools where "identical retry" is a loop rather than a probe | M |
| MORE | process count | Two interpreter launches per tool call, every call | W:4-26 both unconditional | ~50-150 ms latency per tool call; on slow disks or AV-scanned Windows more | 10 s timeout | Acceptable; could skip `success` for non-edit, non-failing tools via `if` filters | L |
| LESS | timeout | 10 s too short under load | W:11 | Output discarded; `PreToolUse` fail-open (E5); a `failure`/`success` write lost -> state drift | Fail-open is by design | Acceptable | L |
| AS WELL AS | manifest description | Describes a component that does not exist ("fresh-context reviewer at Stop", M:4) while R:12 says there is no Stop hook and must not be re-added | Stale manifest after the Stop hook was removed | Users and marketplaces are told the plugin reviews at Stop; a reader trusts a control that is absent; contradicts the README | None | Fix M:4 | M (F19) |
| PART OF | wiring | Only `failure`, `success`, `gate` wired; `edit` alias (H:252) unused; no `SessionStart`/`SessionEnd` | H:17, W | No state cleanup, no self-test, no reset on resume | n/a | See Node 4 | L |
| OTHER THAN | event semantics | Hooks assumed sequential per tool call | E4: parallel batches, background Bash completions | See Node 4 concurrency | None | See Node 4 | M |
| EARLY/LATE/BEFORE/AFTER | wiring order | n/m: ordering among the three events is fixed by Claude Code | | | | | |
| REVERSE | n/m | | | | | | |

---

## Node 2: Payload ingestion and error extraction (`H:85-94`, `H:166-170`, `H:257-268`)

**Design intent.** Read `tool_name`, `tool_input`, `session_id`, `scratchpad_dir` from stdin JSON
(R:26) and, on failure, the error text via `error` / `tool_response{error,message,stderr,stdout}` /
`result` / `output` (H:86-93). Any exception exits 0 silently (H:266-268).

**Parameters.** Inputs: payload fields per E1/E2. Outputs: `tool`, `tool_input`, error string.
Environment: Claude Code payload schema at the installed version.

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| NO | error text | `extract_error` returns "" on the documented failure payload | Keys read are `error`, `tool_response`, `result`, `output` (H:86); documented payload has `tool_error`, `tool_output`, and `tool_response` as an object whose only text is inside `content[].text` (E1); sub-keys checked are `error/message/stderr/stdout` (H:91) | `sig` empty -> `if sig:` false (H:182) -> signature never recorded -> reminder never fires. The component R:8 calls the plugin's "main value" (count surviving compaction) is silent always-pass, exactly the mode C:19 calls "worse than no check" | T:19 fixtures use `error`, so the tests pass; R:26 warns of this failure mode but the test cannot detect it | Read `tool_error` first, then `tool_output`, then `tool_response.content[*].text`; add a fixture copied from a real payload | H (F1) |
| OTHER THAN | error text | If a tool's `tool_response` is a plain non-empty string (not documented for Bash) it is used verbatim as the "error" | H:88-89 | Signature built from a non-error string (e.g. "error", or the tool's text output); all failures of that tool collapse to one signature | None | As above | M (F1) |
| AS WELL AS | failure kinds | `is_interrupt` ignored; user-refused `PermissionRequest` and tool timeouts counted as failures | H:166-177 never read `is_interrupt`; E1 | Node 5/6: user interrupts and refusals arm the gate | None | Return early when `is_interrupt` is true; optionally skip when `tool_error` indicates a permission refusal | H (F5, F6) |
| NO | `tool_input` | Missing or non-dict | `payload.get("tool_input", {})` (H:168) and `canonical_call` handles non-dict (H:71) | Key computed on `null`/list; harmless | ok | none | n/m |
| NO | `tool_name` | Missing | "unknown" (H:167) | All unnamed tools share counters | never happens in practice | none | L |
| NO | payload | Not JSON / not a dict | H:263-265 | Exit 0, nothing done (T:44) | by design | none | n/m |
| MORE | payload size | Very large `tool_input` (big Write contents) | `json.dumps` of the whole input (H:81) hashed per call | CPU/memory only; fine | | | n/m |
| PART OF | payload | `scratchpad_dir` absent (pre-2.1.257 or unavailable) | H:108 falls back to `tempfile.gettempdir()` | See Node 4 | | | M (F15) |
| REVERSE / EARLY / LATE / BEFORE / AFTER | n/m for a stateless parser | | | | | | |

---

## Node 3: Error-signature computation (`H:45-58`, `H:180-193`)

**Design intent.** Reduce the first line of the error to a coarse, stable signature (lowercase,
strip pytest `E` prefix, mask hex, timestamps, `/tmp` paths, line numbers, all integers; 160-char
cap) and count per `tool + signature` (H:183). "Coarse on purpose" (R:40).

**Parameters.** Input: error string (Node 2). Output: `sig`, `sk`, count. State: `signatures` map,
never reset. Timing: on every failure.

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| NO | signature | Empty (see Node 2 NO) | H:47-48, 182 | Reminder dead | | | H (F1) |
| LESS | discrimination | First line only (H:49) + integer masking (H:56). Once the field is fixed, Bash `tool_error` is "Command failed with exit code 1" (E1), so every non-zero Bash exit has signature `command failed with exit code <n>` | H:49, H:56 | Reminder fires on the second unrelated Bash failure in a session ("same signature") and escalates "occurrence N; the previous remedy was too low" (H:158-162) for the rest of the session; counts never reset (no decay, no clear on success) | R:40 says coarse on purpose, but this is total collapse for the main tool | Build the signature from `tool_output` (first non-boilerplate line, e.g. last line or first line matching `error|fail|exception`), or from exit code + last line | M (F2) |
| MORE | discrimination | First line is volatile (progress bar, timestamp without `T`, PID, hostname) | H:49-56 masks only certain forms | Two identical failures get different signatures; reminder never fires | | As above | L (F2) |
| AS WELL AS | content | Signature text is raw tool output embedded into `additionalContext` (H:148-149) | Error text can come from untrusted sources (repo test output, fetched pages) | Up to 160 chars of attacker-controlled text re-injected under the plugin's voice; lowercased and number-masked, so low impact | 160 cap, H:145-146 phrasing is declarative | Quote/escape and label as untrusted, or omit the text | L (F20) |
| PART OF | masking | `/tmp/\S+` only; `$TMPDIR`, `/var/folders/...`, Windows temp paths not masked | H:53 | Platform-dependent signature stability | | mask `tempfile.gettempdir()` prefix | L |
| OTHER THAN | key | Keyed on tool + signature, not call | H:183 | Two different commands with the same coarse signature are "the same failure"; by design (R:40) | | ok | n/m |
| REVERSE | count | Never decremented or cleared on success (H:200-213 touch only `calls`) | | Escalating message long after the problem was fixed | | Clear the signature entry when the same call succeeds, or decay by time | L (F2) |
| EARLY/LATE/BEFORE/AFTER | n/m | | | | | | |

---

## Node 4: State file and its lifecycle (`H:107-135`, `H:195`, `H:213`)

**Design intent.** One JSON file per session at
`<scratchpad_dir or tempdir>/hdc-state-<session_id>.json` (H:107-111), holding `edit_epoch`,
`signatures`, `calls` (H:122-124). Written atomically via `<path>.tmp` + `os.replace` (H:130-133).
Survives compaction (R:8). Fail-open on any OS/JSON error (H:118, H:134).

**Parameters.** Inputs: `scratchpad_dir`, `session_id`. State: file; `.tmp` sibling. Timing:
load-modify-save in each of `failure`, `success`; load in `gate`. Concurrency: any number of
simultaneous processes (E3, E4). Environment: filesystem, tempdir permissions, session resume (E6),
Claude Code version (E2).

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| NO | state | Cannot read (missing, torn, non-dict) | H:118-121 -> `{}` | Fresh state: counters lost, gate open (fail-open) | by design | none beyond concurrency fix | L |
| NO | state write | `save_state` fails (dir missing, read-only, quota) | H:134 `pass` | Every write lost; silent always-pass; indistinguishable from "no repeats" | none | log once to stderr; self-test | M (F17) |
| MORE | writers | Concurrent hook processes (parallel batch post-hooks, background Bash completion, parallel subagents) all do load-modify-save with the same `.tmp` name | H:130 single tmp name; no lock; E3, E4 | Lost update: e.g. batch `[Edit a.py, Read b.py]` -> both load epoch=3; Edit writes 4; Read's hook writes its copy with epoch=3 -> edit bump lost -> gate stays closed after a real edit. Also: a failure record lost (fail-open), or process B truncates A's half-written `.tmp` while A replaces it -> torn JSON -> state reset | `os.replace` atomic per writer only | Use `fcntl.flock` on a lock file around load-modify-save, or a unique tmp name (`tempfile.NamedTemporaryFile(dir=...)`) plus a lock; or make `success` skip the save when nothing changed | M (F10) |
| MORE | lifetime | Never deleted; persists across `--resume` (E6) | No `SessionEnd`; H:107-111 keyed by session only | Stale gate state days later: the user fixed files meanwhile (outside Edit tools) -> first retry on resume denied; tempdir accumulates files on older versions | | `SessionStart` hook resets `calls`; or record wall-clock and expire | M (F7) |
| OTHER THAN | location | `scratchpad_dir` absent -> system tempdir | H:108; E2 (v<2.1.257) | File in shared `/tmp` with default umask (0644): world-readable `desc` holds up to 120 chars of command text (H:103) which can include tokens/URLs; predictable name; `.tmp` symlink-following `open(..., "w")` (H:131) | session_id is a UUID (hard to guess) | `os.open` with 0600, `os.makedirs(..., mode=0o700)` subdir; prefer `${CLAUDE_PLUGIN_DATA}`/session-scoped dir | L (F15) |
| OTHER THAN | key | `session_id` shared by all subagents (E3) | H:109 | One state for main agent + all subagents; see Node 7 | | key on `agent_id` too, or keep per-agent `calls` | M (F9) |
| PART OF | key | `session_id` missing -> "unknown" | H:109 | All sessions share a file; cross-session false denies | never per docs | none | L |
| AS WELL AS | contents | State readable/writable/deletable by the agent via Bash (`rm "$scratchpad/hdc-state-*.json"`) | path derivable from plugin source + scratchpad in payload/system prompt | Agent can "delete past" the gate; C:29 claims only "edited past" | none | Not fully fixable; note in docs; store outside scratchpad | L (F11) |
| REVERSE | atomicity | `os.replace` on Windows across AV scans can raise `PermissionError` | H:133 -> swallowed | write lost | | retry once | L |
| LATE | save | Hook timed out before `save_state` | 10 s (W:11) | update lost; fail-open | | n/m in practice | L |
| EARLY | load | `gate` loads before the previous call's `failure` hook finished | Sequential in the main loop; only in batches (E4) | Two identical calls in one batch both pass | rare | n/m | L |
| BEFORE/AFTER | n/m beyond the above | | | | | | |

---

## Node 5: PreToolUse gate (`H:216-246`, `mode gate`)

**Design intent.** Deny iff identical call AND failed >= 2 times AND no successful edit since the
last failure (R:32; H:221-227). Deterministic, narrow; "it blocks; it does not remind" (R:7);
labelled Engineer. Deny reason tells the agent to change code/input/approach or, for transient
errors, say so and vary the call (H:229-238).

**Parameters.** Inputs: `tool_name`, `tool_input`, state. Outputs: nothing, or
`permissionDecision: deny` + reason. Timing: before every tool call, before permission prompts.
Environment: any tool (no matcher), user interactive or headless.

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| NO | deny | Gate does not fire for a true loop | Any of: state lost (Node 4), key differs because of an ignored-but-real difference (Node 6), trivial variation (`2>&1`, `; true`, `bash -c '...'`, `-v`) | Loop continues cosmetically varied; harder for a human to spot than an identical loop | R:34 calls variation a deliberate escape hatch; deny text itself instructs it (H:236-238) | Count by a looser key as well (e.g. tool + first token/path) for the reminder; make the deny text ask for a stated reason rather than "vary the call"; log the denial as a `systemMessage` so the human sees it | M (F11) |
| OTHER THAN | failure meaning | Gate counts every `PostToolUseFailure`, which includes failures that are not mistakes: `grep` with no match (exit 1), `diff`, `test -e`, `git diff --exit-code`, polling `curl localhost:8080` until a server is up, `WebFetch` on a flaky network, Ctrl+C interrupts (E1), user permission refusals (E1), Bash timeouts | H:173-177 unconditional; `is_interrupt` ignored | Third identical poll/probe denied; the agent must do a dummy edit or vary the command; a user who interrupted twice and says "run it again" gets a deny claiming the command "has failed 2 times" | Deny text offers the escape hatch | Skip `is_interrupt`; skip refusals; for Bash use exit code heuristics (exit 1 from grep/diff/test) or only arm on exit codes >1, or require `tool_output` non-empty; allow an explicit user override (`permissionDecision: ask`) | H (F4, F5, F6, F21) |
| MORE | sensitivity | Count is cumulative over the session; after any edit one more failure re-arms the gate (`count` 3 >= 2, epoch equal) | H:175 never reset by edits; H:224-226 | Post-fix: exactly one attempt per edit; a flaky test or a tool whose first run initialises and second run passes is denied; message "has failed N times" (H:230-231) counts failures before earlier fixes | T:40-41 shows this is intended | Reset `count` to 0 (or 1) when an edit occurs, so the rule is "failed twice since the last change" | M (F12) |
| MORE | scope | Applies to all tools (W:5) incl. Read/Grep/Glob/WebFetch/Agent/AskUserQuestion/MCP | no matcher | Probe-style tools where identical retries are legitimate (Read of a file that is being generated, WebFetch after a transient 503) are denied | | matcher or allowlist | M (F4) |
| LESS | message accuracy | Deny reason says "no file has been edited since the last failure" | Marker is Edit-tool success, not file change (Node 7) | Statement is false when the user or Bash edited the file; the agent is told to "change the code" it already changed | | Reword: "no successful Edit/Write tool call since"; better, fix the marker | M (F7) |
| AS WELL AS | headless | In `-p`/CI the deny goes only to the model; no `systemMessage` | H:240-246 | Human never learns the gate fired; a model can oscillate deny/vary indefinitely costing tokens | | add `systemMessage` on deny | L |
| AS WELL AS | user override | No way for the human to say "yes, run it unchanged" except disabling the plugin or editing a file | R:41 suggests editing the source to use "ask" | Confusing UX; user is told to vary a command they asked to re-run | | ship `ask` as a `userConfig` option; honour an env var `HDC_DISABLE=1` | M (F13) |
| REVERSE | decision | `allow` never emitted; n/m | | | | | |
| EARLY | timing | Gate fires before permission prompt; a deny pre-empts the user's own decision | | fine | | | n/m |
| LATE | timing | Hook timeout -> tool proceeds (E5) | | fail-open | | | L |
| BEFORE | ordering | `gate` runs before `failure` of a sibling call in the same parallel batch (E4) | | two identical calls in one batch both pass | | | L |
| AFTER | ordering | `gate` after `--resume` sees stale state (E6) | | Node 4 MORE lifetime | | | M (F7) |

---

## Node 6: Canonical-call key, "identical" (`H:64-82`)

**Design intent.** Same tool + same input after dropping `description`, `timeout`,
`run_in_background` (H:64,72) and collapsing whitespace inside every string (H:75); SHA-1 prefix
(H:82). So `pytest  x.py` == `pytest x.py` (R:34).

**Parameters.** Inputs: `tool_name`, `tool_input` (any tool's schema). Output: 16-hex key.

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| LESS | discrimination | Whitespace inside quoted/structured strings collapsed: `Edit.old_string`/`new_string`, `python -c "..."`, heredocs writing Makefiles (tabs) or Python, `printf`, grep patterns | H:75 applies to all string values recursively | Concrete: `Edit` fails "old_string not found" twice; the third attempt with corrected indentation (the usual fix) is "identical" and denied; Edit failures don't bump the epoch, so the only way out is an unrelated edit or `Write` | none | Collapse whitespace only for `Bash.command`, and only outside quotes; never for Edit/Write fields | H (F3) |
| LESS | discrimination | `timeout` dropped | H:64 | A command that timed out twice (a failure per E1) cannot be re-run with a larger timeout, which is the correct fix | R:38-39 do not mention it | Keep `timeout` in the key, or treat a timeout increase as a change | H (F21) |
| LESS | discrimination | `description`/`timeout`/`run_in_background` dropped for every tool, not only Bash | H:72 | MCP or custom tools with a genuine `description`/`timeout` parameter (issue trackers, HTTP tools): two semantically different calls are one key -> false deny | | Apply `IGNORED_INPUT_FIELDS` only when `tool == "Bash"` | M (F14) |
| LESS | context | `cwd`, worktree, environment, and the Bash tool's persisted working directory not part of the key | H:81 uses only tool+input; payload `cwd` unused | `pytest` failing in dir A then run after `cd B` (separate call) or after `EnterWorktree` is "identical"; denied in a different checkout | | Include payload `cwd` in the key | L (F16) |
| MORE | discrimination | Any other field difference is a different call: `dangerouslyDisableSandbox`, `shell`, a trailing comment `# retry`, `; true` | H:72, H:81 | Trivial evasion; also perverse incentive: the cheapest "variation" may be a privilege flag such as `dangerouslyDisableSandbox: true` | R:34 accepts this | See Node 5 NO; add a `systemMessage` on deny | M (F11) |
| OTHER THAN | hash | SHA-1 16-hex prefix collision | negligible | | | | n/m |
| AS WELL AS | key inputs | `tool_input` not a dict (string) | H:71 skips filtering; still hashed | ok | | | n/m |
| REVERSE/EARLY/LATE/BEFORE/AFTER | n/m for a pure function | | | | | | |

---

## Node 7: "Has anything changed" marker, the edit epoch (`H:40`, `H:176`, `H:207-211`, `H:226`)

**Design intent.** A successful `Edit`/`Write`/`MultiEdit`/`NotebookEdit` increments `edit_epoch`
(H:210-211); a failure records the epoch at the time (H:176); the gate opens if the epoch moved
(H:226-227). "It cannot be talked past, only edited past" (C:29). A call that succeeds clears its own
count (H:207).

**Parameters.** Inputs: tool name of successful calls. State: `edit_epoch`, `calls[*].epoch`.
Environment: the real filesystem and git state, which the marker does not observe; subagents (E3).

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| NO | bump on real change | Change made by Bash (`sed -i`, `cat <<EOF >`, `git checkout`/`stash pop`/`pull`, `npm install`, `pip install`, `export VAR`, `chmod`), by the human in an IDE, by a formatter/pre-commit, by another process, or by a file edited before `--resume` | `EDIT_TOOLS` only (H:40, H:210) | Gate stays closed after a genuine fix; deny reason falsely claims nothing was edited; agent must perform a dummy Edit or vary the command | none | Fingerprint the working tree instead: e.g. `git status --porcelain` + hash of changed-file mtimes/sizes, or hash `git diff` output, computed at failure time and compared at gate time; bump also on `Bash` commands matching `>`/`sed -i`/`git`/package managers | H (F7) |
| MORE | bump on non-change | Any successful Edit/Write anywhere bumps: a scratch file, `NOTES.md`, the plugin's own README | H:210 ignores `file_path` | The documented procedure (C:31: append `repeat: ...` to `NOTES.md` when you notice a repeat) is itself an Edit that reopens the gate, so following the rules guarantees the unchanged retry is allowed; also any trivial `Write` to the scratchpad is a bypass | C:29 says "edited past" is the only way, which is accurate but is the vulnerability | Bump only for files under `cwd` that are not notes/docs, or (better) use a tree fingerprint as above | H (F8) |
| OTHER THAN | actor | A subagent's successful Edit (same `session_id`, E3) bumps the main agent's epoch; a subagent's failure of `npm test` counts toward the main agent's key and vice versa; two parallel subagents running the same failing command each add to the shared count | H:109, H:210 | Subagent denied on its first attempt ("has failed 2 times") because the parent or a sibling failed; parent's gate reopened by an unrelated subagent edit | | Keep `calls` per `agent_id` (payload field) and bump epochs per agent, or include `agent_id` in the state path | M (F9) |
| REVERSE | marker | Edit then `git checkout -- .` via Bash reverts the change; epoch stays bumped | H:210 one-way | Gate open though the code is back in the failing state; the loop resumes | | tree fingerprint | L (F7) |
| PART OF | edit success | `Edit` that succeeds but changes nothing (`replace_all` on no-op?) or edits an unrelated file | | bump without change | | tree fingerprint | L |
| AS WELL AS | clear on success | `success` pops the call key for any tool (H:207) including when the same key succeeds in a subagent | | consistent | | | n/m |
| EARLY/LATE | epoch recorded | `call["epoch"]` set at failure time (H:176): an Edit that happened *during* a long-running failing command (parallel batch or background) is counted before the failure, so the gate still closes | E4 | rare; conservative | | | L |
| BEFORE/AFTER | n/m beyond above | | | | | | |

---

## Node 8: PostToolUseFailure reminder (`H:144-197`, `mode failure`)

**Design intent.** On the Nth identical signature inject a factual reminder as
`additionalContext` (H:188-193), declarative wording to avoid tripping injection defences (H:145-146);
escalate beyond threshold (H:158-162). Labelled "Engineer detector, Administer nudge" (R:8).

**Parameters.** Inputs: Node 2/3 outputs. Outputs: `additionalContext` text <= ~700 chars. Timing:
after a failure, before the model's next turn.

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| NO | reminder | Never emitted on documented payload | Node 2 NO | Component absent; doc claims (R:8, C:29) false | | fix field names | H (F1) |
| MORE | reminder | Fires on every failure once count >= 2 (H:187), never resets; with collapsed signatures (Node 3 LESS) fires on nearly every Bash failure | H:187; no reset | Noise; the "occurrence N, previous remedy too low" text (H:160-161) is wrong when the failures were unrelated; model habituates to the message | | reset on success; better signature | M (F2) |
| LESS | reminder | Signatures too volatile (Node 3 MORE) | | never fires | | | L |
| OTHER THAN | wording | Text says "failed N times with the same signature" where the signature may be e.g. `command failed with exit code <n>` | H:148-149 | Misleading summary to the model | | include `describe_call` desc too | L |
| AS WELL AS | content | Includes raw error text (Node 3 AS WELL AS) | | injection surface | | | L (F20) |
| PART OF | audience | `additionalContext` reaches the model only; no `systemMessage` to the human | H:188-193 | Human unaware a repeat was detected | | add `systemMessage` | L |
| EARLY/LATE/BEFORE/AFTER/REVERSE | n/m | | | | | | |

---

## Node 9: PostToolUse bookkeeping (`H:200-213`, `mode success`)

**Design intent.** Pop the succeeding call's key; bump epoch on edit tools (R:9).

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| MORE | writes | Load + save on every successful tool call even when nothing changed (H:203-213) | | Widens the race window of Node 4; each Read/Grep rewrites the file | | save only if state changed | L (F10) |
| OTHER THAN | timing | For `run_in_background` Bash, `PostToolUse` fires asynchronously at completion (E4) | | concurrent writer (Node 4) | | lock | M (F10) |
| NO | pop | Hook lost (timeout/race) | | a stale failed-call record stays; next identical call after two prior failures denied although it has since succeeded | | lock | L |
| AS WELL AS | tools | `MultiEdit` may no longer exist; harmless | H:40 | | | | n/m |
| LESS/PART OF/REVERSE/EARLY/LATE/BEFORE/AFTER | n/m | | | | | | |

---

## Node 10: Messages emitted to the agent (`H:144-163`, `H:229-238`)

**Design intent.** Factual, non-imperative text (H:145-146); deny reason names the loop and asks
for a rung-named change; offers the transient-error escape hatch (H:236-238).

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| OTHER THAN | instruction | Deny text instructs "vary the call in a way that reflects that judgement" | H:236-238 | Trains the trivial-variation bypass; an agent optimising to proceed will add `-v` or `2>&1`; the human sees a varied, not identical, loop | R:34 accepts | Replace with "state to the user why re-running unchanged is expected and ask them to confirm" and use `ask` | M (F11) |
| LESS | accuracy | "no file has been edited since the last failure" (H:231-232) and "failed N times" (H:230) | Nodes 5, 7 | False when files were changed outside Edit tools or when failures were interrupts/refusals/pre-fix | | reword; fix marker | M (F7) |
| OTHER THAN | rung label | Reminder says resolving to be careful is "Protect-rung" (H:150-152); S:27 says Protect; C:25 says Administer | | The framework's own classification of its central example is inconsistent across the three texts the agent may have loaded at once | | pick one (C:25's reasoning is the more careful one) and align | M (F18) |
| MORE | length | n/m (far under 10k cap) | | | | | |
| NO | message | Reminder never emitted (F1) | | | | | H |
| AS WELL AS | imperative | Reminder contains "should be named by rung", "is preferred" | H:152-156 | Mildly imperative despite H:145-146; acceptable | | | n/m |
| REVERSE/EARLY/LATE/BEFORE/AFTER | n/m | | | | | | |

---

## Node 11: Tests (`T`)

**Design intent.** Fifteen assertions walking a fake session through failure, reminder, gate,
reopening, clearing, garbage input (R:26). Isolated via `TMPDIR` (T:7-8). To be run after any Claude
Code update because "a renamed field fails as silent always-pass" (R:26).

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| OTHER THAN | fixture shape | Fixtures use `error` (T:19,21), `tool_response:{}` (T:24-26); documented payload uses `tool_error`/`tool_output`/`tool_response{content}` (E1) | Hand-written fixtures | Tests pass while the reminder is dead in production; the suite cannot perform the job R:26 assigns it (catching a renamed field) because it never sees a real payload | R:28 manual check covers the gate only, never the reminder | Capture a real `PostToolUseFailure` payload (a `PostToolUseFailure` hook that `tee`s stdin) into `test/fixtures/` and assert on it; add a manual reminder check to R:28 | H (F1, F17) |
| NO | coverage | No tests for: `scratchpad_dir` path, `is_interrupt`, timeout change, Edit whitespace case, MCP `description`, subagent sharing, concurrent writers, resume | T:28-45 | The false-positive surface R:46 calls "close to the definition of the loop" is untested | | add cases | M |
| LESS | isolation | Relies on `tempfile.gettempdir()` honouring `TMPDIR` (T:7) and on no `scratchpad_dir` in fixtures | fine | | | | n/m |
| PART OF | assertion | `check` uses substring match (T:14); `"permissionDecision": "deny"` string depends on `json.dumps` spacing | H:139 default separators | brittle but currently correct | | | n/m |
| AS WELL AS | side effects | `set -u` but no `set -e`; failing python invocations in T:38,42 are unchecked | | minor | | | n/m |
| MORE | count claim | R:26 says fifteen; T has 15 `check` calls | verified | | | | n/m |
| REVERSE/EARLY/LATE/BEFORE/AFTER | n/m | | | | | | |

---

## Node 12: Documentation and rules as procedure (`R`, `C`, `D`, `S`)

**Design intent.** State each component's rung honestly (R:3-10); rules for classifying fixes (S,
C); procedure for the agent's own repeats: notice, append to `NOTES.md`, build the highest rung
(C:23-40); claims: count survives compaction (R:8), gate cannot be talked past (C:29), test after
updates (R:26), install path (R:18-20).

| Guide word | Parameter | Deviation | Cause (evidence) | Consequence | Safeguards | Recommendation | Sev |
|---|---|---|---|---|---|---|---|
| OTHER THAN | claim | R:8 "The count survives compaction, which is its main value" and C:29 "reports when the same failure signature recurs" | F1 | Claims false on the documented payload | | fix code, then re-verify claim | H (F1) |
| OTHER THAN | own rule | C:19 "Any hook ... must be exercised against a real payload before it is relied on" and C:18 "a check that reads a field the payload does not contain fails as silent always-pass, which is worse than no check" | The shipped reminder is that case; R:26 admits the suite is a fake session | The plugin fails its own acceptance criterion; the README's Engineer/Administer labels for the reminder rest on an unverified mechanism | | Add the real-payload fixture (Node 11) and a `SessionStart` smoke test | H (F1, F17) |
| OTHER THAN | claim | M:4 Stop reviewer vs R:12 "There is no Stop hook" | stale | contradiction | | fix M:4 | M (F19) |
| OTHER THAN | label | S:27 Protect vs C:25 Administer vs H:150 Protect for the same example | | inconsistency in the taxonomy the plugin exists to teach | | align | M (F18) |
| OTHER THAN | claim | R:7 / C:29 "no file edit since", "only edited past" | Node 7 | The marker is "Edit-tool success", not "file edit"; both broader (any file) and narrower (not Bash/human edits) than stated | | reword or fix | H (F7, F8) |
| AS WELL AS | procedure interaction | C:31 instructs appending to `NOTES.md` on a noticed repeat | Node 7 MORE | Following the rule reopens the gate | | exempt notes files from the bump, or fingerprint tree | H (F8) |
| LESS | scope statement | R:45-48 known limits list exit-0 wrong answers, narrowness, Cowork; they omit: failures that are not mistakes (interrupts, probes, polling), non-Edit changes, subagent sharing, concurrency, trivial variation being an evasion path | | User's risk picture incomplete | | extend Known limits | M |
| PART OF | install | R:18 `tar xzf ... -C ~/.claude/skills` loads as `@skills-dir` with hooks (E7): holds. R:14 "Plugins do not load a CLAUDE.md": holds (E7). R:20 "Hook changes need /reload-plugins": holds | verified | none | | | n/m |
| MORE | rule strength | C:20 warns that a narrow gate "carries a false-positive cost on unrelated work ... say what would justify removing it"; R:46 says the false-positive surface is "close to the definition of the loop" | Nodes 5-7 show a wide surface | The README under-states the cost its own rules say to state | | enumerate the surface in README | M |
| REVERSE | framework application | R:41 tells users to make the gate `ask` by editing source; `userConfig` exists for this | | Administer where Engineer (config) is available | | `userConfig` option | L (F13) |
| NO | user control | No env/config off switch; no visibility of denials to the human in headless runs | | | | | L (F13) |
| EARLY/LATE/BEFORE/AFTER | n/m for documents | | | | | | |

---

## Coverage summary

| Node | Rows | Credible deviations (F#) |
|---|---|---|
| 1 Wiring/manifest | 9 | F17, F19 |
| 2 Payload/extraction | 10 | F1, F5, F6, F15 |
| 3 Signature | 9 | F1, F2, F20 |
| 4 State file | 12 | F7, F9, F10, F11, F15, F17 |
| 5 Gate | 13 | F4, F5, F6, F7, F11, F12, F13, F21 |
| 6 Canonical key | 8 | F3, F11, F14, F16, F21 |
| 7 Edit epoch | 9 | F7, F8, F9 |
| 8 Reminder | 9 | F1, F2, F20 |
| 9 Success bookkeeping | 7 | F10 |
| 10 Messages | 9 | F7, F11, F18 |
| 11 Tests | 8 | F1, F17 |
| 12 Docs/rules | 11 | F1, F7, F8, F13, F17, F18, F19 |

12 nodes, 104 rows (including n/m rows), 21 findings.

Team viewpoints applied: hook runtime (E1-E8), concurrency/filesystem (Node 4, 9), git internals
(Node 7 NO/REVERSE), the constrained agent including an evasive one (Nodes 5, 6, 7, 10), the human
user (Node 5 OTHER THAN / user override, Node 12), the framework's own labels (Nodes 10, 12).
