# HAZOP: tested, not adopted

Process safety finds its scenarios with a HAZOP before it judges its safeguards with LOPA and ranks its fixes with the hierarchy of controls. This repo has the last two steps ([protection-layers.md](protection-layers.md), [the ladder](hierarchy-of-defect-controls.md)) and no systematic first step, so HAZOP was the obvious candidate. It was tested before being adopted, and it is not adopted. This page records why, so the question does not have to be reopened from scratch.

## The method

A Hazard and Operability study (ICI, 1960s; IEC 61882) takes a frozen design and divides it into nodes, each with a stated design intent. For each node, a team applies guide words to the node's parameters to generate deviations: no flow, more pressure, reverse flow, other than the intended material, too early, too late. For each deviation the team records the causes, consequences, existing safeguards and recommendations. Software variants (CHAZOP, Def Stan 00-58) apply the same guide words to data flows and signals.

Its value comes from two things: systematic coverage, and a team whose members see the design differently. Its known costs are time, tedium, and worksheets that decay into boilerplate.

## The test

A retrodiction test with a control arm ([evidence](evidence/hazop-retrodiction/README.md)):

- **Subject:** the plugin's v0.1.0 design, the exact package review round 1 examined.
- **Arms:** two HAZOP desk studies and two plain expert design reviews, on the same model with the same materials and effort.
- **Scoring:** a blind judge scored each run against the 76 findings that seven rounds of adversarial review actually produced.

| | Plain review (2 runs) | HAZOP (2 runs) |
|---|---|---|
| Round 1's 18 findings matched | 13, 13 | 13, 11 |
| New correct findings | 5, 3 | 4, 7 |
| Incorrect findings | 0, 0 | 1, 2 |
| Generic findings | 0 | 0 |

## Why it is not adopted

1. **It found no more of what mattered.** Recall of the known findings was the same or lower, at the same cost plus a worksheet of 95 to 104 rows. Its lean toward more new findings came with all of the incorrect ones, on two runs per arm.
2. **The blind spot was not a coverage problem.** Every run of either kind missed the same things: what Claude Code actually delivers to which hook (a failed Edit fires none; a failure hidden by a pipe arrives as a success). Every incorrect or unverifiable claim in either arm was of that kind. Guide words can prompt the question "what if no event arrives?", but reading cannot answer it. Round 1 answered it by logging real payloads in a live session.
3. **Its real source of value is not available here.** HAZOP's strength is a team that reads the design differently. A single model running the method systematically is still one reading, and the two HAZOP runs converged on the same core findings as the two plain reviews. This is the independence argument from [protection-layers.md](protection-layers.md) applied to the analysis itself.

## What is kept

**Observation before documentation.** Everything in this repo's history that a reading missed was found by running something:
- the event routing, which round 1 found with a payload logger;
- the 2.1.289 deny wrapper, found by a live check;
- the deny-rule bypasses and the git-index route, found by scripted live sessions ([evidence](evidence/)).

The test supports the existing practice: claims about runtime behaviour are checked live and recorded with the version before a doc relies on them.

**Guide words as a brainstorming checklist, not a method.** Applied to an agent's working loop, they generate candidate scenarios cheaply. For example:
- *more* on a tool call is a retry loop, which the gate covers;
- *less* on an edit is a successful no-op, which the no-op detector covers;
- *early* on verification is "tests pass" reported from a run older than the last edit.

A candidate earns further work only if it can be observed, for instance counted from transcripts the way the [indicators](indicators.md) count gate denies. The last example, edits after the last test run, is such a candidate. It has not been built.

**Three findings no review caught**, which several study runs agreed on and which still hold for the current code by reading:
- a user's interrupt counts as a failure, because `is_interrupt` is never read;
- the temp-directory state fallback keeps command text under a predictable name and never cleans it up;
- error text is quoted unfiltered into the hook's own messages.

They are listed in the [evidence](evidence/hazop-retrodiction/README.md#new-findings-several-runs-agreed-on) and have not yet been confirmed live or fixed.

## When to revisit

- **When independent readers exist.** That means a real team, or analyses given genuinely different information, such as one working from captured payloads and another from the code.
- **For a workflow that does not exist yet.** With no code to read, plain review has less to grip and systematic enumeration may matter more. That was not tested here.
