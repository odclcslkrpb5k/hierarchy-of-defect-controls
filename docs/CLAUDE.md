# Hierarchy of Defect Controls

When proposing a fix, remediation, or postmortem action item, or when correcting your own mistake, classify the remedy on this ladder before presenting it. The ladder covers code defects and mistakes in analysis, measurement, and operations alike; only the examples differ.

1. **Eliminate** - the mistake has nowhere to happen. Code: remove the mechanism, feature, or dependency. Analysis: do not derive it by hand; ask the system that already knows (a client-side census over 600 records becomes one server endpoint).
2. **Substitute** - swap in something that makes the mistake much harder to produce. Code: safer language, vetted library, ORM, `Decimal` for money. Analysis: the instrument that cannot make the error (cgroup accounting rather than wall-clock deltas around a process tree).
3. **Engineer** - the mistake is possible but a deterministic check catches it. Code: types, lints, CI gates, pre-commit and tool-use hooks, schema validation, DB constraints. Analysis: a control arm, a negative control, an assertion that the mechanism fired at all, a counter proving the measured thing actually happened.
4. **Administer** - process asks people not to make the mistake: review, standards, checklists, docs, comments, conventions, resolving to be more careful.
5. **Protect** - the defect ships and is absorbed downstream: monitoring, alerting, backups, retries, kill switches, defensive handling. Analysis: stating the limits beside the finding so a wrong conclusion is caught before it is acted on.

## Rules

- Name the rung of every proposed fix, and name the next rung up with the reason it was not chosen: "Engineer fix; Eliminate would mean removing the coercion layer, which touches every query." Names, not numbers.
- For an Administer or Protect fix, that reason must say what the Engineer control would be and why it is not proportionate. Do not silently default to "add a comment and a test".
- Prefer the highest rung whose cost is proportionate to the defect's blast radius and recurrence. Do not propose architectural changes for defects an assertion would catch. Do not propose an assertion for a defect that has recurred three times.
- Administer and Protect fixes are legitimate when chosen deliberately. Flag them; do not refuse them.
- When a codebase relies on review to catch the same bug class repeatedly, say so and name the Engineer control that is missing.
- A control for a repeated mistake must be specific to that pattern and deterministic. A generic self-review, a prose-reading gate, or a check that fires on acknowledgement of a mistake is not an Engineer control; it is Administer wearing a gate, and a gate on disclosure prices honesty.
- Any hook or check you add must be exercised against a real payload before it is relied on. A check that reads a field the payload does not contain fails as silent always-pass, which is worse than no check.
- Before saying a change is verified, run the checks that existed before it, unmodified, and report their result apart from tests you wrote. A test whose expected answer came from your own reading of the problem shares that reading's mistakes.
- Do not weaken or disable a check (a skip marker, a looser assertion, a config or workflow edit) so that your own change passes, unless the task asks for it, and name every check you changed. If a check looks wrong, say so instead of changing it.
- A narrow gate built from one session's mistake carries a false-positive cost on unrelated work. Scope it as tightly as the pattern allows and say what would justify removing it. Gate accumulation is height-seeking in slow motion.
- Treat the rung as a property of the fix, not a judgement of the author.

## Your own repeated mistakes

The ladder applies to you. When the same mistake happens twice in a session (wrong path, forgotten step, same class of bug, same misread of an API, same wrong accessor into a response), do not resolve to be more careful. That is Administer with nothing written down, addressed to the attention that just failed, and it will fail again as the context grows.

Detection and persistence are different problems.

**Detection.** Hooks from the `hierarchy-of-defect-controls` plugin act on tool failures. A `PreToolUse` gate denies a call identical to one that has already failed twice with the same error when nothing has changed since: no edit-tool write, no working-tree change, no new commit. A new user message also reopens it; that is the path for fixes made outside the session such as an environment change. A trailing shell comment will get past it, so do not treat it as a wall. A `PostToolUseFailure` reminder reports when the same failure signature recurs; treat its message as a noticed repeat, not as noise to retry past. A simple `sed -i` or `perl -pi` that reports success while leaving its operand files byte-identical is recorded as a failure; whether you then act on that is still up to you. A repeated `git apply` or `patch` fails on its own, so the gate covers it without a detector. None of these sees an Edit rejected by validation, a non-zero exit hidden by a pipe, or a wrong answer with exit code 0. Silent repeats are not reliably detectable in general, and no mechanism here claims to detect them. What is cheap is recording one when you do notice.

**Persistence.** When you notice a repeat, append one line to the project's notes file (`NOTES.md` unless the project names another) in the form `repeat: <pattern> (<date>)`. The recording is Administer, since it depends on you remembering to write it, but the record makes the count a `grep -c` instead of a recollection, and the three-times threshold above is a lookup against that file, not a memory. Check it before choosing a rung.

Then build the highest rung you can right now, specific to the pattern you just repeated:

- **Eliminate**: change the approach so the mistake has nowhere to happen. Generate the repetitive code from a schema instead of writing it by hand. Use one helper instead of the same sequence in five places. Replace a hand-derived count with a query.
- **Substitute**: switch to a tool or library that does the step for you.
- **Engineer**: add a test, assertion, type, lint rule, or script check that fails when this specific mistake is made. For a wrong accessor, one typed accessor module validated against a fixture, so a shape change fails loudly. For a mistake in how you edit files or run commands, a `PreToolUse` hook that rejects the pattern before the tool runs, or a git pre-commit check, is usually the strongest control available and usually cheap. Propose one before proposing a CLAUDE.md line, and test it against a real payload.
- **Administer**: propose a line for CLAUDE.md or the project's docs. It persists across sessions, but it is still a request to remember. Choose it only when no Engineer control is practical.

Say which rung you chose, the next rung up, and why it was not taken. A second recurrence after you noticed the first means the chosen rung was too low.
