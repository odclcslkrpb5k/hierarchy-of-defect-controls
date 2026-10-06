# HAZOP retrodiction test: method, prompts, results

2026-10-06. Evidence for [hazop.md](../../hazop.md). The question was whether a HAZOP (Hazard and Operability study) applied to this plugin's design finds the defects that adversarial review later found, and whether it finds more than an unstructured expert review given the same materials.

## Design

- **Subject.** The plugin as of v0.1.0, from the release archive of 2026-09-14, the exact package that review round 1 ([01-v0.1.0.md](../../reviews/01-v0.1.0.md)) examined. It has 8 files, including a 272-line hook script. A read-only copy was provided; it contains no review text.
- **Two arms, two runs each, all on one model (Claude Fable 5.1), run in parallel:**
  - **HAZOP** (`hazop-h1`, `hazop-h2`): IEC 61882-style, adapted to software as in CHAZOP and Def Stan 00-58. The analyst divides the design into nodes, states each node's design intent and parameters, applies the guide words NO/NOT, MORE, LESS, AS WELL AS, PART OF, REVERSE, OTHER THAN, EARLY, LATE, BEFORE and AFTER, and takes a team's viewpoints.
  - **Plain review** (`review-r1`, `review-r2`): a thorough expert design review, told to consider the same angles, with no method prescribed.
- **Identical constraints in both arms:**
  - read only the subject and Claude Code's public documentation;
  - no other files, git history, reviews or web search for the plugin;
  - execute nothing (desk study only);
  - write a findings list in a shared JSON format, in plain language with no method vocabulary.
- **Ground truth** (`ground_truth.json`): another agent extracted every distinct finding from review rounds 1 to 7, 76 in all, without seeing either arm.
- **Blind judge** (`judge-scores.json`, `judge-summary.md`):
  - **Inputs:** the four findings lists, shuffled under the labels run A to D. The key is in `blinding-key.json`, which the judge was told not to read.
  - **Applicability:** it decided which ground-truth findings apply to v0.1.0 (24: 19 fully, 5 partly).
  - **Matching:** it scored each run match, partial or miss on each, crediting only the specific mechanism.
  - **Unmatched findings:** it classified each one as new-correct, new-unverifiable, incorrect, generic or duplicate. It was allowed to use the reviews' real-session evidence to check correctness.

Effort was matched: 122k to 144k tokens and 15 to 20 tool calls per run. The two plain-review runs first failed on a safeguard false positive triggered by asking for notes on "how you reasoned"; they were rerun with that phrase replaced by "the evidence behind each finding", otherwise unchanged.

## Results

Key: run A = `review-r1`, B = `hazop-h2`, C = `hazop-h1`, D = `review-r2`.

| | Review A | Review D | HAZOP B | HAZOP C |
|---|---|---|---|---|
| Findings | 24 | 19 | 20 | 21 |
| Applicable ground truth (24): matched / partial / missed | 16 / 1 / 7 | 16 / 0 / 8 | 16 / 0 / 8 | 12 / 5 / 7 |
| Round 1's findings on this exact version (18): matched | 13 | 13 | 13 | 11 |
| New, verifiably correct | 5 | 3 | 4 | 7 |
| New, unverifiable by reading | 4 | 2 | 1 | 0 |
| Incorrect | 0 | 0 | 1 | 2 |
| Generic | 0 | 0 | 0 | 0 |

- **Recall:** no difference between arms. Three of four runs matched exactly 13 of round 1's 18 findings. HAZOP run C matched fewer because of one wrong premise, that the payload has no `error` field, which round 1's captured payloads refute. That premise turned several of its other findings into partial matches.
- **New findings:** HAZOP averaged 5.5 new correct findings to the plain review's 4, and produced all three incorrect ones. With two runs per arm this is a lean, not a result.
- **Boilerplate:** none in any findings list. The HAZOP worksheets ran to 95 and 104 rows, many recorded as "not meaningful"; the tedium went into the worksheet, not the findings.
- **Shared blind spot:**
  - **Event routing.** No run found that a failed Edit fires no hook at all (R1-C1); three built scenarios on the opposite assumption. Only one run found that a non-zero exit hidden by a pipe arrives as a success (R1-C2). Every incorrect or unverifiable claim in any run concerned what Claude Code delivers to which hook. Round 1 settled those facts by logging payloads in a real session.
  - **Labels.** Every run missed the two label findings that argue from the framework's own definitions against the reminder (R1-F1) and the success bookkeeping (R1-F3), though every run made the equivalent argument against the gate.

## New findings several runs agreed on

None was in any review. As of v0.7.1, by reading the code; none confirmed live:

- **Interrupts count as failures.** `is_interrupt` is never read (captured payloads carry it), so a user's interrupt counts as an agent failure toward the gate.
- **The state-file fallback leaks command text.** When a payload has no `scratchpad_dir`, as in `-p` sessions, state goes to the system temp directory under a predictable name (`hdc-state-<session>.json`), holds up to 120 characters of each failing command, and is never removed.
- **Error text reaches the model unfiltered.** The normalised error signature, up to about 180 characters of tool output, is quoted into the hook's own reminder and deny messages, an unfiltered channel from tool output into text the hook presents as its own.

## Caveats

- Two runs per arm, one model for every role, one judge.
- The ground truth was extracted by a model from the reviews, not curated by hand.
- Both arms were desk-only by design; the real reviews also ran code and live sessions, which is how they found the runtime facts no desk run did.
- This tests HAZOP as a method for reviewing a code design. It does not test HAZOP as a way to enumerate scenarios for an agent's working loop.

## Prompts

The constraints block (subject path, read-only rules, docs allowed, no execution) and the output format were identical in both arms. The parts that differed:

**HAZOP arm, method section:**

> 1. Divide the design into nodes: each hook entry point/mode, the state file and its lifecycle, the error-signature computation, the "has anything changed" marker/fingerprint, the messages emitted to the agent, the manifest/hook wiring, the tests, and the documentation and rules as procedural nodes. Add others if the design suggests them.
> 2. For each node, state its design intent (from the docs and code) and its parameters: inputs (payload fields, values), outputs (decisions, messages), state, timing and ordering, concurrency, environment (git, filesystem, Claude Code version, subagents).
> 3. Apply guide words systematically to each node's parameters: NO/NOT, MORE, LESS, AS WELL AS, PART OF, REVERSE, OTHER THAN, EARLY, LATE, BEFORE, AFTER. For each meaningful deviation record: cause(s) with file:line evidence, consequence, existing safeguards, and a recommendation. Briefly note combinations you judge not meaningful, so coverage is visible.
> 4. HAZOP is a team method. Bring the viewpoints a team would: the hook runtime and payload format, concurrency and the filesystem, git internals, the AI agent being constrained (including one that tries to get around it), the human user, and the framework the docs claim to apply (do the docs' own claims and labels hold?).

**Plain-review arm, task section:**

> Find the defects, risks, failure modes and inaccuracies in this design and implementation: anything that would make it fail its stated intent, harm the user or the agent's work, or make its own documentation untrue. Consider it from every angle an experienced reviewer would: the hook runtime and payload format, concurrency and the filesystem, git internals, the AI agent being constrained (including one that tries to get around it), the human user, the tests, and the framework the docs claim to apply (do the docs' own claims and labels hold?).

## Files

| File | What |
|---|---|
| `ground_truth.json` | 76 findings from review rounds 1 to 7 |
| `hazop-h1.*`, `hazop-h2.*` | HAZOP runs: worksheet and findings |
| `review-r1.findings.json`, `review-r2.findings.json` | Plain-review runs |
| `judge-scores.json`, `judge-summary.md` | The blind judge's applicability, matching and classification |
| `blinding-key.json` | Run label to arm |
