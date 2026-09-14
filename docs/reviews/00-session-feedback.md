# Hierarchy of Defect Controls — proposed revision

Two changes: widen the ladder past defects in shipped code, and close the detection gap left when
the Stop reviewer was removed. Written from using the deployed `CLAUDE.md` on a live project for a
session, plus reading the original package in `hierarchy-of-defect-controls.tgz`.

---

## 1. The Stop reviewer was correctly removed

All four objections hold, and the first is fatal on its own.

**It punishes honesty.** The hook fires only when `last_assistant_message` *acknowledges* a repeat,
then blocks. That prices disclosure: the cheapest way past the gate is to not say it. This is not a
tuning problem, it is a design inversion — a control that makes the behaviour it wants more
expensive than the behaviour it is trying to prevent. Blameless postmortems exist because this
failure mode is well understood.

**It checks wording, not substance.** A fast model reading prose for "did they name a rung and
build something above Protect" is grading rhetoric. `"This is an Engineer fix: I'll note it"`
passes. Combined with the first objection this is worse than no control, because it converts a
practice into a performance and then certifies the performance.

**It inherits the detection problem.** It fires on acknowledgement, so it depends on the model
having noticed — the attention the skill says cannot be trusted.

**It is expensive.** Up to 30 s of model call on every stop for a rare event. Weakest objection
alone; you would pay it for a control that worked.

**It may see nothing.** `last_assistant_message` was never confirmed to be in the Stop payload.
This one deserved a test rather than an argument, because the failure mode if the field is absent
is *silent always-pass* — a control that reports success while doing nothing. The package ships
`test/run_tests.sh` and `test/failure.json` for the counter and nothing for the reviewer, so the
one component whose correctness was uncertain was the one left unexercised.

Worth noting in passing: `README.md` classifies the Stop hook as **Substitute**. It substitutes
nothing. It inspects output and blocks — Administer with a gate, at best. The framework applied to
its own components was already slipping.

## 2. But removing it left the requirement unserved

`repeat_counter.py` is a genuine Engineer control: deterministic, outside the model, no dependence
on noticing. It covers repeats **that fail a tool**.

Most do not. Four times in one session I read a value out of an API response with the wrong
accessor — `props` for `properties`, nested `group` for `groupId`, resolved values counted as
owned. Every one returned a plausible wrong answer with exit code 0. A string replacement that
silently matched nothing once reported `8/8 passed` for a spike that never ran. No tool failed. The
counter saw none of it.

The deployed `CLAUDE.md` is honest about this — *"Most repeated mistakes never fail a tool, so
noticing the rest is still on you"* — and that sentence is Administer addressed to the attention
that just failed, which is the exact thing the document forbids two paragraphs earlier. **The doc
currently violates its own rule at its most important point.**

## 3. The reframe: stop trying to detect repetition

Every mechanism for detecting repetition *in general* is unreliable (a model reading prose),
perverse (a gate on self-disclosure), or expensive (a model call per stop). That is not bad luck.
Generic detection requires semantic judgement over open-ended behaviour, and there is no cheap
deterministic form of it.

The way out is that **you do not need to detect repetition. You need to detect the specific thing
you just did twice** — and once you know what that is, a deterministic check is usually trivial.

From this session, three repeats and the narrow control each one implies:

| repeat | deterministic control |
|---|---|
| Scripted edit whose anchor silently matched nothing, then reported success | A `PreToolUse` check rejecting a heredoc that calls `.replace(` without asserting the anchor first |
| Wrong accessor into an API response | One typed accessor module, fixture-validated, so a shape change fails loudly |
| A negative control that asserted the absence of an outcome rather than the mechanism | A convention, checked at review: a control asserts *why* it was refused, not merely that it was |

None of those requires noticing a repeat at the moment it happens. Each is specific, cheap, and
fails loudly. So the rule the document is missing is not "notice harder" but:

> **A control for your own repeated mistake must be specific to that pattern and deterministic. A
> generic self-review is not an Engineer control — it is Administer wearing a gate.**

## 4. Detection and persistence are different problems

Worth separating, because conflating them is what made the Stop reviewer look necessary.

- **Detection** — knowing a mistake happened. Solved for tool failures by the counter. Unsolved for
  silent ones, and honestly unsolvable in general. Say so plainly.
- **Persistence** — knowing, later, *how many times*. Entirely solvable, and cheap.

Persistence is what actually gated my remedy choice. I knew each time that I had done it before; I
could only justify building a type layer because I had been appending the near-misses to a project
notes file for unrelated reasons. Without that the threshold rule — *"do not propose an assertion
for a defect that has recurred three times"* — silently degrades to a guess.

So: a write-down obligation with a fixed location, which is Engineer rather than Administer because
the count becomes a `grep -c` instead of a memory. It does **not** solve detection, and should not
be sold as if it does.

## 5. Widening past code defects

The rungs generalise; only the examples are narrow. Every serious mistake I made this session was a
**measurement or analysis error, not a coding error**, and the document gave me no vocabulary for
those. The strongest controls in that kind of work are experimental.

Proposed examples to add per rung:

| rung | code | analysis, research, operations |
|---|---|---|
| **Eliminate** | remove the mechanism or dependency | do not derive it by hand — ask the system that already knows. A census walked client-side over 607 records became one server endpoint |
| **Substitute** | safer language, vetted library, `Decimal` for money | use the instrument that cannot make the error — cgroup accounting rather than wall-clock deltas around a process tree |
| **Engineer** | types, lints, CI gates, schema validation | **a control arm**; a negative control; an assertion that the mechanism fired at all. A counter proving the thing being measured actually happened |
| **Administer** | review, standards, checklists | a checklist in a skill file; a documented convention |
| **Protect** | monitoring, retries, backups | state the limits beside the finding, so a wrong conclusion is caught downstream rather than acted on |

The Engineer row is the one that would have paid. A CPU experiment of mine concluded "resource
blocking costs 11% more" and reached a design document before review caught it; the arm measured
interception overhead, not blocking. A pass-through control arm — an Engineer control, unnamed as
such in the current text — turned the wrong number into the right one. I got there by instinct,
after the fact, and only because someone reviewed it.

One wording change while widening: *"the bug class can no longer exist"* reads as being about code.
**"the mistake has nowhere to happen"** covers both a removed dependency and a hand-count replaced
by a query.

## 6. Concrete edits

1. **Cut** the last sentence of the hook paragraph — *"so noticing the rest is still on you"* — and
   replace it with the honest split from §4: the counter covers tool failures; silent repeats are
   not reliably detectable; what is cheap is recording one when you do notice.
2. **Add** the specificity rule from §3, as its own bullet under *Rules*.
3. **Add** a write-down obligation with a named location — the project's notes file — and restate
   the three-times threshold as a lookup against it rather than a recollection.
4. **Widen** the five rung definitions with the second column of §5, and change Eliminate's gloss
   to "the mistake has nowhere to happen".
5. **Do not** re-add a Stop reviewer. If the gap still feels open after 1–4, the next thing to build
   is another deterministic `PreToolUse` check for whatever pattern has actually recurred — not a
   general-purpose reader of the model's own prose.
6. **If any hook is re-added**, test that its input payload contains the field it reads. The one
   uncertainty in the package was in its only untested component.

## 7. Does the ladder work? — one session's *hypothesis*

Read this as a hypothesis generated from inside the treatment condition, not as a result. The claim below is introspection about a counterfactual, produced by the same process that produced the output being explained, with the rules already in context. §8 says what would actually settle it.

It may have changed an outcome. Faced with a fourth wrong-accessor mistake, the
answer I was about to give was *"I'll verify response shapes before believing a count"* — Administer
with nothing written down, addressed to the attention that had just failed four times. The rung
vocabulary made that visibly inadequate, and *"propose a hook before proposing a CLAUDE.md line"*
pushed to a typed accessor module, which is now a tracked deliverable rather than an intention.

Naming the next rung up and why it was not taken is the rule that earned the most: *"Eliminate would
mean generating these types from the server's schema, which is not right while the API is days old"*
is a judgement someone else can disagree with. Without the rule it would have been invisible.

The risk to watch as it spreads is height-seeking — building a hook for a genuine one-off because
the ladder rewards altitude. The proportionality rule guards against it, but it held for me because
I was being asked to justify cost, not because the ladder naturally lands there.

---

## 8. Can this be measured at all?

The rules are in the context of every session that could report on them, so the participant is the
wrong instrument. That is a real limit, but it is narrower than it looks: it makes **self-report**
unreliable, not **measurement** impossible.

- **Within a session the counterfactual is unrecoverable.** Nothing said about what would otherwise
  have happened is better than a plausible story.
- **Across sessions there is no contamination.** A session without the rules is a clean control.
  Sessions are independent samples; this is ordinary A/B testing.

### The design that fits

Repeated mistakes are rare and unpredictable, so waiting for them in live sessions is not a plan.
**Replay is the way around it.** Take a transcript in which a repeat occurred, truncate immediately
before the remediation turn, and run that prefix N times with the rules present and N times with
them stripped. Everything up to the decision point is held constant; only the treatment differs.

Metrics, ordered by resistance to contamination:

1. **Was a checkable artifact produced?** Binary and visible in the diff — a type, a hook, a test, a
   script check, versus a resolution or a comment. No self-report. Primary.
2. **Blind rung classification of the remedy.** Strip every rung label from both arms and have a
   judge who does not know the arms classify each proposed fix. This tests the mechanism rather than
   the vocabulary, which matters because the treatment arm will *say* "Engineer" and the control
   will not — a difference that measures nothing.
3. **Recurrence.** Does the same mistake happen again later in the run? The outcome actually worth
   having, and the only one that distinguishes a control from a performance. A remedy chosen more
   often that does not reduce recurrence is cost without benefit.
4. **Cost.** Response length and time spent on remediation. The ladder could make sessions longer
   for no gain.

### The contamination that cannot be designed away

**Demand characteristics.** With the rules in context the model knows rung-naming is being assessed
and will name rungs. That inflates metric 2 unless it is blinded, and can inflate metric 1 —
building an artifact to satisfy the rule rather than because it fits. Metric 3 is the only one that
cannot be satisfied by performing, which is why it belongs in the design even though it is the
hardest to collect.

The same applies to asking a session to report when the rules were useful. That is a leading
question; the design feedback it produces is real, but it is self-report and should not be weighed
as efficacy evidence.

### What uncontrolled observation still earns

Applicability (do situations arise where the rules bite), friction (the rungs fit shipped defects
better than process mistakes), failure modes (the detection gap; the README's own misclassification
of its Stop hook), and the existence of artifacts. That is iteration data, and it is honest as long
as it is not presented as efficacy.

### The decision may not need the evidence

The cost of the rules is roughly a page of context and some response length. The cost of a missed
Engineer control is a defect that recurs indefinitely. Against that asymmetry the bar for wider
deployment is *absence of harm plus a plausible mechanism*, not a measured effect size — which is
just as well, because with events this rare, detecting a modest effect against run-to-run variance
would take a great many paired runs.

The measurement worth buying is therefore the cheaper, commoner one: **does it lengthen responses
or push toward disproportionate fixes?** Those are the failure modes that would make it
net-negative, they occur often enough to observe without a replay harness, and neither needs a
counterfactual.
