# Indicators

The ladder says which control to build. Indicators say whether it is working. This page adapts API RP 754, the process-safety indicator standard for refining and petrochemicals, to the plugin's controls, and is as explicit about what the numbers cannot say as about what they can.

## The original

RP 754 followed the 2005 Texas City refinery explosion. The Baker Panel found that BP had leaned on personal-injury rates, which looked good, as evidence of process safety, which was decaying. The standard separates the two and sorts process-safety events into four tiers:

- **Tier 1 and 2**: loss of primary containment, split by fixed consequence thresholds. Lagging.
- **Tier 3**: challenges to safety systems: a demand on a safety system, an excursion past a safe operating limit. Leading.
- **Tier 4**: operating discipline and management-system performance. Leading.

Each event is counted once, against definitions fixed in advance, so that the count does not depend on who is doing the counting.

## The mapping

| Tier | Here | Source | Measured |
|---|---|---|---|
| 1 | A defect from an agent session caused harm after it left the session | none | no |
| 2 | A defect left the session and was caught before harm | none | no |
| 3 | A demand on a control: gate deny, repeat-failure reminder, no-op edit detected | transcripts, `scripts/hdc_report.py` | yes |
| 4 | A control found impaired: a hook exception swallowed, a corrupt state file | `HDC_EVENTS` log | partly |

### Why Tiers 1 and 2 are not measured

RP 754 defines them by consequence. The obvious software proxy, a revert of a commit carrying an agent `Co-Authored-By` trailer, was measured on the machine this was built on: no reverts in 372 trailer commits across 8 repositories, and in 7 of the 8 every commit carries the trailer, so it separates agent changes from almost nothing. A revert is a response rather than a consequence, and squash merges and fix-forward never show up as one. More basically, the hooks act on in-session retry loops, whose cost is wasted calls, not escaped defects; no Tier 3 count here predicts a Tier 1 or 2 count of anything. Logging them by hand would be possible, and would be an Administer control.

### Why a gate deny is Tier 3

A deny is the control working. So is a relief valve lifting, and RP 754 counts that in Tier 3 because the demand is the precursor: the process reached the point where only the safety system stood between it and a loss. A deny means the same here: the agent reached a third identical call with nothing changed. The reminder is an alarm on the way to the same point, so it is folded into the same episode rather than counted as a separate challenge.

### Counting rules

- **Episode** (the primary unit): Tier 3 events with the same error signature, or for a no-op the same call, within one user turn of one transcript. A reminder followed by a deny is one episode of depth 2.
- **Continued past the gate**: an episode with two or more denies, so the agent re-issued a call that had already been denied, unchanged. This is the closest thing to a loss of containment that the hooks can see.
- **Exposure**: `tool_use` blocks in main and subagent transcripts. Denied calls and Edits rejected by validation are included; both are tool calls.
- **Denies cleared by a user turn**: a denied call issued again after the next user message. This is the gate's cost in human messages. It is not a false-positive count: a user message is the designed escape when the fix happened outside the session, and a transcript cannot say which it was.
- **Rate**: episodes per 1,000 tool calls with an exact Poisson 95% interval, printed only from 20 episodes up.
- **Tier 4**: counts, not a rate. Any non-zero count is a finding.

## Reading the numbers

**Events are rare.** Outside the plugin's own test sessions, the machine this was built on recorded 2 reminders and no denies in about 11,900 tool calls (13 sessions, 151 subagent transcripts) over the plugin's first three weeks installed. The exact 95% interval on 2 events runs from 0.24 to 7.2, so a halving and a doubling cannot be told apart for months. That is why the report prints counts and refuses a rate below 20.

**The Texas City caveat.** Tier 3 counts retry loops: frequent, cheap and visible. It says nothing about wrong answers with exit code 0, which are rare, expensive and invisible to every hook here. A falling Tier 3 count is not evidence of fewer defects, and must not be read as one.

**The indicator moves with the control.** Tier 3 is the hazard rate multiplied by the control's sensitivity. Changing `THRESHOLD`, or a signature fix like 0.5.1's glued-unit normalisation (which let more loops arm the gate), moves the count with no change in agent behaviour. Transcripts do not record the plugin version, so compare only windows within one release, using `--since`. Tier 4 records carry the version and threshold.

**Zero Tier 4 is not evidence of health.** Most ways the hooks degrade never reach the logged exception handler: `tree_state` swallows git errors, `file_hash` returns `None`, a renamed payload field makes `extract_error` return an empty string so reminders silently stop, and a hook that never runs leaves nothing at all. The guard against those is the test suite with captured fixtures, not this log.

**None of this measures efficacy.** Whether the controls change what the agent does needs the replay A/B design in [`reviews/00-session-feedback.md`](reviews/00-session-feedback.md) ("The design that fits"). These indicators measure exposure, demand and cost.

## Goodhart rules

- **Indicators stay out of the model's context.** Nothing in `SKILL.md` or `CLAUDE.md` mentions them, and no hook injects a count. A model told its deny rate can lower it by varying a command trivially (a trailing comment gets past the gate), which is the wrong behaviour. This holds for the hooks; the report is a CLI an agent can run and read like anyone else, so keeping it out of the agent's hands is a request, which is Administer.
- **They are not targets.** A rising Tier 3 count can mean more loops, a more sensitive control, or simply more work.
- **They are never computed from what the agent says about itself**, for the same reason there is no Stop hook: a measure built on disclosure prices honesty.

## Use

    python3 scripts/hdc_report.py                # this project
    python3 scripts/hdc_report.py --all          # every project
    python3 scripts/hdc_report.py --since 2026-10-01 --json

**Transcripts** are read from `$CLAUDE_CONFIG_DIR/projects` (default `~/.claude/projects`). Their format is undocumented and may change with a Claude Code upgrade; the parser is tested against captured excerpts from two versions (`test/fixtures/transcript_*.jsonl`) and against the hooks' current messages. Re-capture after an upgrade: the report prints the Claude Code versions it read, and a version newer than the newest fixture is the prompt. In `-p` sessions the stored form of a deny changed between 2.1.270 and 2.1.289, and until the parser was taught the new form it counted none. Every stored deny seen so far comes from a `-p` session; the interactive form has not been observed. Claude Code deletes transcripts after `cleanupPeriodDays`, so the window is rolling. A project means sessions started in that directory; sessions started in a subdirectory are a separate project (use `--project` or `--all`). Turn boundaries are inferred: task notifications and slash-command bookkeeping are not counted as user turns.

**The Tier 4 log** is opt-in: set `HDC_EVENTS` to an absolute path in the environment Claude Code runs hooks in. Each record holds a timestamp, schema, plugin version, threshold, kind (`hook_exception` or `state_corrupt`), session id, and for exceptions the hook mode, exception type, function and line. No command or error text is written. A corrupt state file is recorded once, by the next hook that takes the state lock and rewrites it. The file is created with mode 0600. A symlink, FIFO, device or directory is refused; a hung filesystem can still block the write, as it can the state file. The log grows without limit; rotate it yourself.
