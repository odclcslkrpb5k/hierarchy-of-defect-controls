# Hierarchy of Defect Controls

![The five rungs, widest at the top](hierarchy-of-defect-controls.svg)

A ranking of software remediations from most to least effective, adapted directly from the occupational-safety Hierarchy of Controls (NIOSH). The name is deliberate: if you know the original, you already know this.

## The original

In industrial safety, hazard mitigations are ranked by how little they depend on humans doing the right thing every time:

1. **Elimination** - remove the hazard entirely
2. **Substitution** - replace it with something less dangerous
3. **Engineering controls** - isolate people from the hazard (guards, interlocks, ventilation)
4. **Administrative controls** - change how people work (procedures, training, signage)
5. **PPE** - protect the individual at the point of exposure (gloves, respirators)

The ordering is the whole point. The top rungs work regardless of behaviour. The bottom rungs work only while people are attentive, trained, and not tired. Organisations instinctively reach for the bottom because it is cheap and fast; safety culture exists to push them upward.

## The software mapping

Same five rungs, same ordering, applied to defects instead of hazards.

### 1. Eliminate
The bug class cannot exist because the thing that produces it is gone.

- No shared mutable state, so no data races
- No string-built SQL, so no injection
- No manual memory management, so no use-after-free
- Delete the feature, the dependency, or the code path

### 2. Substitute
The bug class is still conceivable but you have swapped in something that makes it much harder to produce.

- A memory-safe language for a memory-unsafe one
- A vetted parsing library for a hand-rolled parser
- An ORM query builder for string concatenation
- `Decimal` for floats when the value is money

### 3. Engineer
The mistake is possible, but the system catches it before it ships or before it does damage.

- Type systems, compiler warnings as errors, "make illegal states unrepresentable"
- Linters, static analysis, CI gates that block the merge
- Schema validation at boundaries
- Database constraints (foreign keys, NOT NULL, unique indexes)
- Feature flags with kill switches, immutable infrastructure

### 4. Administer
Process. The system will not stop the mistake; people are asked to.

- Code review
- Coding standards and style guides
- Runbooks, checklists, PR templates
- Pairing, training, onboarding docs
- "Remember to update the changelog"
- "Be careful" comments, and resolving to be more careful

### 5. Protect (PPE)
The defect reaches production and the individual or the organisation absorbs it.

- Monitoring, alerting, on-call
- Backups and restore procedures
- Defensive error handling at the edges
- Retries, circuit breakers, graceful degradation

Protect is necessary. Every system needs it. It is also the last line, and it fails exactly when the human is least able to respond.

## How to use it

### As a diagnostic
The framework earns its keep in postmortems and code review. When a proposed remediation is "add a note to the wiki" or "remind the team", that is an Administer control, and the question to ask is whether an Eliminate or Engineer fix exists for the same defect. When a codebase relies on review to catch the same bug class repeatedly, that is a signal that a type, a constraint, or a lint rule is missing.

The vocabulary makes this discussable without it landing as personal criticism. "That's an Administer fix" is a statement about the fix, not the author.

### The proportionality rule
This is the part that keeps the framework from becoming a stick.

> Prefer the highest rung whose cost is proportionate to the defect's blast radius and recurrence.

In industry the hierarchy is nearly universal because the physics does not change. In software the cost of the upper rungs varies wildly. Rewriting a service in Rust is a Substitute fix and is almost never proportionate to a single bug. A one-line assertion is an Engineer fix and is nearly always proportionate. An Administer fix for a low-frequency, low-impact defect is a perfectly good decision, provided it is a decision and not a default.

The failure mode of the framework is dogmatism: people proposing architectural changes for bugs a test would catch. The point is to make the rung visible so the trade-off is explicit, and then to make the trade-off honestly.

### In practice
When proposing a fix, name its rung. Use the name, not the number; "Administer" carries its meaning and "rung 4" does not. If it is Administer or Protect, say whether a higher-rung fix exists and why you did not choose it. That single habit is most of the value.

### Applying it to AI agents
The ladder applies to an agent's own mistakes the same way. When a coding agent notices it has made the same error repeatedly in a session and resolves to be more careful, that is an Administer fix with nothing written down, addressed to the attention that just failed, in a context that is only getting longer. The useful response is the same as for a human team: name the rung, then look for an Engineer control that can be built immediately (a test, an assertion, a lint rule, a script check) or an Eliminate change (restructure the work so the mistake has nowhere to happen). A note in the project's instruction file is Administer; it persists across sessions, which beats an in-session resolution, but it is still a request to remember.

## Related ideas

- **Poka-yoke / mistake-proofing** (Toyota, lean): Engineer applied to manufacturing
- **"Make illegal states unrepresentable"** (Yaron Minsky): Engineer at the type level
- **Shift left**: the ordering principle, expressed as time rather than mechanism
- **Blameless postmortems** (Dekker, Allspaw, Google SRE): the culture that discourages "be more careful" as a remediation
- **Secure by Design** (CISA, OWASP): the same layering applied to vulnerabilities
- **Swiss cheese model** (Reason): often confused with this; it explains how failures pass through layers rather than ranking which layers to build
- **Layer of Protection Analysis** (CCPS): which layers deserve credit at all. Its qualitative half, independence above all, is applied to agent work in [protection-layers.md](protection-layers.md)
- **HAZOP** (ICI, IEC 61882): how process safety finds scenarios in the first place. Tested against this repo's own review history and not adopted; [hazop.md](hazop.md) records why
