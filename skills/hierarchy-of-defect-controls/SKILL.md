---
name: hierarchy-of-defect-controls
description: Rules for classifying any fix, remediation, postmortem action item, or self-correction on the Hierarchy of Defect Controls (Eliminate, Substitute, Engineer, Administer, Protect). Use whenever proposing how to prevent a bug, incident, or repeated mistake, including your own repeated in-session mistakes.
---

# Hierarchy of Defect Controls

When proposing a fix, remediation, or postmortem action item, or when correcting your own mistake, classify the remedy on this ladder before presenting it:

1. **Eliminate** - the bug class can no longer exist (remove the mechanism, the feature, or the dependency)
2. **Substitute** - swap in something that makes the bug class much harder to produce (safer language, vetted library, ORM, `Decimal` for money)
3. **Engineer** - the mistake is possible but the system catches it (types, lints, CI gates, schema validation, DB constraints, feature flags)
4. **Administer** - process asks people not to make the mistake (review, standards, checklists, docs, comments)
5. **Protect** - the defect ships and is absorbed (monitoring, alerting, backups, retries, defensive handling)

## Rules

- State the rung of every proposed fix by name, not number. One word is enough: "This is an Engineer fix." Numbers express the ordering; names are the labels.
- If the fix is Administer or Protect, say whether a higher-rung fix exists and why you did not pick it. Do not silently default to "add a comment and a test".
- Prefer the highest rung whose cost is proportionate to the defect's blast radius and recurrence. Do not propose architectural changes for defects an assertion would catch. Do not propose an assertion for a defect that has recurred three times.
- Administer and Protect fixes are legitimate when chosen deliberately. Flag them; do not refuse them.
- When a codebase relies on review to catch the same bug class repeatedly, say so and name the Engineer control that is missing.
- Treat the rung as a property of the fix, not a judgement of the author.
- Before saying a change is verified, run the checks that existed before it, unmodified, and report their result apart from tests you wrote. A test whose expected answer came from your own reading of the problem shares that reading's mistakes.
- Do not weaken or disable a check (a skip marker, a looser assertion, a config or workflow edit) so that your own change passes, unless the task asks for it, and name every check you changed. If a check looks wrong, say so instead of changing it.

## Your own repeated mistakes

The ladder applies to you. When you notice you have made the same mistake more than once in a session (wrong path, forgotten step, same class of bug, same misread of an API), do not resolve to be more careful. That is Administer with nothing written down, addressed to the attention that just failed, and it will fail again as the context grows.

Instead, stop and name the rung of what you are about to do, then look for a higher one you can build right now:

- **Eliminate**: change the approach so the mistake has nowhere to happen. Generate the repetitive code from a schema instead of writing it by hand. Use one helper instead of the same sequence in five places.
- **Substitute**: switch to a tool or library that does the step for you.
- **Engineer**: add a test, assertion, lint rule, type, or script check that fails when the mistake is made. A shell alias or a one-line pre-commit check counts. This is usually the right rung and is usually cheap.
- **Administer**: propose a line for this file or the project's docs. This is persistent across sessions, which makes it better than an in-session resolution, but it is still a request to remember. Prefer it only when no Engineer control is practical.

Say which rung you chose and why. If you chose Administer or Protect, say what Engineer control you considered and why it was not proportionate. A second recurrence of the same mistake after you noticed the first is a strong signal the chosen rung was too low.
