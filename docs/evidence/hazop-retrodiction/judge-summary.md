# Judge summary: four desk analyses of hierarchy-of-defect-controls v0.1.0

Ground truth: 76 findings. Applicable to v0.1.0 as provided: 19 (all 18 round-1 findings plus R2-REMEDY, whose text exists at hdc_hooks.py:158-162). Partly applicable: 5 (R2-R3-ENV, R2-R6, R2-F3, R5-R6-residual, R7-RUNG-COST). Not applicable: 52 (fingerprint, no-op detector, report, indicators, protection-layers doc, run_tests.py and later-version doc text).

Matching is scored over the 24 applicable-or-partly findings. "Round 1" restricts to the 18 round-1 findings.

| | run_A | run_B | run_C | run_D |
|---|---|---|---|---|
| Findings in run | 24 | 20 | 21 | 19 |
| Applicable GT matched / partial / missed (24) | 16 / 1 / 7 | 16 / 0 / 8 | 12 / 5 / 7 | 16 / 0 / 8 |
| Round-1 GT matched / partial / missed (18) | 13 / 1 / 4 | 13 / 0 / 5 | 11 / 2 / 5 | 13 / 0 / 5 |
| Run findings that map to GT | 15 | 14 | 12 | 14 |
| new-correct | 5 | 4 | 7 | 3 |
| new-unverifiable | 4 | 1 | 0 | 2 |
| incorrect | 0 | 1 | 2 | 0 |
| generic | 0 | 0 | 0 | 0 |
| duplicate | 0 | 0 | 0 | 0 |

Round-1 misses by run: A: C1, C2, F3, STOPGAP. B: C1, C5, F1, F3, STOPGAP. C: C1, C2, F1, F3, STOPGAP (C6 and C8 partial). D: C1, C2, F1, F3, STOPGAP.

## Ground-truth findings no run found

- **R1-C1** Failed Edits never reach the hooks (validation rejections fire neither PreToolUse nor PostToolUseFailure). Three runs (A F1, C F3, D F3) assumed the opposite and built scenarios on failing Edits being counted and denied.
- **R1-F3** PostToolUse bookkeeping labelled "support" although it decides when the gate reopens.
- **R1-STOPGAP** The silent no-op in-place edit (sed -i that matched nothing) named in docs/CLAUDE.md:29 is detected by nothing.
- **R5-R6-residual** (partly applicable) `\b\d+\b` does not mask digits glued to a unit (5007ms).
- **R7-RUNG-COST** (partly applicable) measured cost of the "name the rung of every fix" rule on plain bug fixes.
- Found by one run only: **R1-C2** (piped/interpreted non-zero exits land in PostToolUse and clear the count) by B only; **R1-F1** (reminder is Administer, not "Engineer detector") only partially, by A.

## Notable

All four runs converge on the same core: the session-keyed state file (subagent sharing, unlocked concurrent writers), the edit-epoch reopen condition (Bash/MCP/IDE/external fixes invisible, any trivial edit including the plugin's own NOTES.md line reopens it), the ignore-list and cosmetic-variation bypass with the deny text instructing it, the stale Stop reviewer in the manifest, the Protect/Administer disagreement, and the hand-written test fixtures. Those are exactly the findings a careful reading of the code yields. The shared blind spot is event routing: what Claude Code actually delivers to which hook. Nobody saw that failed Edits fire no hooks, only B saw that a pipe or an interpreted exit code (grep) routes a failure to PostToolUse, and two runs used grep exit 1 as an example of a counted failure. Both facts were established in round 1 only by running a real session with a payload logger, which a desk analysis cannot do; the runs' weakest claims are precisely the ones about runtime routing (interrupt, timeout, background launch, permission refusal), and the one serious error in the set (C F1, claiming the `error` field does not exist) is of that kind and would have been settled by one captured payload. All runs also miss the two label findings that require arguing from the framework's own Engineer/Administer definitions against the reminder (F1) and the bookkeeping (F3), while every run catches the equivalent argument for the gate (F2).

Run C has the most genuinely new, verifiable findings (cumulative count re-arming after one post-edit failure, ignore-list applied to non-Bash tools, cwd not in the key, no user override) but also the two incorrect findings, one of which (F1) undermines its signature analysis and test-gap finding, reducing them to partial credit. Runs A, B and D are close on ground-truth coverage; A trades a few more unverifiable runtime claims for broader coverage, B is the only run to find C2, and D is the tightest (no incorrect findings, fewest unverifiable). New-correct findings common to several runs and worth adopting: the `is_interrupt` field is never read (docs confirm interrupts and timeouts fire PostToolUseFailure), the tempdir fallback is actually taken in some real sessions (round 6) and stores command text under a predictable name with no cleanup, and the quoted error text is an unfiltered channel into the hook's own message.
