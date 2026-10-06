# Independent protection layers

The ladder ranks a control by its mechanism. The [indicators](indicators.md) count how often a control is called on. Neither asks whether the checks standing between an agent's mistake and its consequence deserve to be counted at all. This page takes that question from Layer of Protection Analysis (LOPA), keeps its qualitative half, and is explicit about the half it leaves out.

## The original

LOPA (CCPS, 2001) sits between a qualitative hazard review and a full quantitative risk analysis; later CCPS texts call it semi-quantitative. For one scenario, an initiating event leading to a consequence, it multiplies the event's frequency by each protection layer's probability of failure on demand and compares the result with a tolerable frequency. Only some safeguards earn credit. CCPS's guidelines on initiating events and independent protection layers (2015) list the core attributes an independent protection layer (IPL) must have:

- **Independence**: of the initiating event, and of every other layer credited in the same scenario.
- **Functionality**: it can actually stop this consequence, in time.
- **Integrity**: the risk reduction reasonably achievable by the layer, given its design and management. In LOPA this is what the failure probability expresses.
- **Reliability**: the probability that it operates to its specification for a specified period.
- **Auditability**: its function can be inspected and tested.
- **Access security**: it cannot be changed or bypassed without authorisation.
- **Management of change**: changes to it are reviewed.

Independence carries the most weight. An alarm that relies on the same sensor as the control loop that failed is not a second layer, and LOPA practice does not credit the operator whose slip started the event as the layer that stops it.

## What is kept, and what is not

Integrity is left out. A probability that a test suite or a code review misses a defect would be invented, and the multiplication would turn that invention into a precise-looking answer. What remains is the qualification step: which safeguards count as layers at all. That is the useful part here, so this page says "independent protection layers" and uses LOPA's name for lineage only, as [indicators.md](indicators.md) does for RP 754.

## Scenarios

Layers are judged against a scenario, not a single change. Two scenarios matter for agent work:

1. **An agent's change carries a defect of some class**: wrong behaviour that exits 0.
2. **An agent weakens a check so that its change passes**: a skip marker, a looser assertion, `|| true` in a workflow.

## Independence is about where the check's answer came from

A check is independent of scenario 1 if its oracle, the expected answer it compares against, did not come from the agent's own reading of the problem. Authorship and timing are not the test. A check the agent builds in-session can be independent, and a test written before the code can be dependent.

| Check | Independent of the agent's reading? | Why |
|---|---|---|
| Tests that existed before the change and that it does not modify | Yes | The oracle predates the change. |
| Type checker or linter whose configuration the change does not touch, and in whose scope the change adds no inline suppression (`# type: ignore`, `# noqa`, `eslint-disable`, `# pragma: no cover`) | Yes, for the defect classes it covers | The oracle is the language or the rule set. A suppression in source silences it as surely as a config edit. |
| A test checked against output captured before the change, or from a system the agent did not write | Yes | The oracle is the system's actual behaviour. This is the typed accessor validated against a fixture in [CLAUDE.md](CLAUDE.md). A snapshot generated from the agent's new code is not this; it captures the reading under test. |
| A spec, acceptance test or review from someone who has not seen the author's framing | Yes | It comes from a different reading. |
| A test the agent wrote from its own understanding, before or after the code | No | The same reading produced the code and the expected answer. Writing the test first catches slips, where the code fails to do what the agent meant; it cannot catch a misreading of what was wanted. |
| The agent's review of its own diff | No | It is the same attention that made the mistake. |
| A second model, or a person, reviewing with the author's description or conversation in view | No | The framing is the common cause. Without it, yes. |
| Any check the change itself edits | No | It fails access security; see below. |

## Common mode: one workflow file

Lint, types and tests usually run from one CI workflow, and one edit to that file silences all three: `|| true`, a deleted job, `continue-on-error`, or `if: false`. A required job skipped by an `if:` condition reports success, so it does not even block the merge. For independence they are therefore one layer, and the workflow file is the common mode. Branch protection can make a named check required, but a `pull_request` workflow runs from the pull request's own copy of the file. A required check is an IPL only if changes to the workflow file are reviewed at a boundary the agent cannot reach; see [access security](#access-security-only-the-merge-boundary-qualifies).

## The ladder and IPLs

The rung is a property of a mechanism. IPL status is a property of a mechanism relative to a scenario. The two do not line up:

- An Engineer-rung check can fail as an IPL, for example a test configuration the agent can edit.
- An Administer control can pass, for example a review by someone without the author's framing.

IPL status does not re-rank the ladder, and it is no reason to refuse an Administer fix. Its use is diagnostic. When the protection on a change rests on layers that fail independence, apply the ladder to that: build a check whose oracle is independent (capture real output, take the acceptance test from the spec), or guard the common mode.

## This plugin, honestly

None of the plugin's controls is an IPL, and neither are the local settings recommended below:

| Control | IPL? | Why |
|---|---|---|
| Gate | No | Trivial variation such as a trailing comment defeats it, and its state file can be written by the agent it constrains. It is a narrow Engineer control, not a layer. |
| No-op detector | No | It feeds the gate. |
| Reminder | No | It works only if the agent acts on it (Administer). |
| Rules (`SKILL.md`, `CLAUDE.md`) | No | Administer. |
| Indicators | Not protection | They provide auditability for the controls. |
| Deny rule on a check file | No | Trivial variation defeats it, the same test the gate fails: `sh -c` around a blocked command gets through. |
| Deny rule plus sandbox | No | The working tree is protected, but the agent can still commit a weakened file through git's index. |

## Access security: only the merge boundary qualifies

An agent that can edit a check can switch it off, so scenario 2 needs a guard the agent cannot get past. Two local guards were tested in `-p` sessions; neither is one.

**A deny rule** (`permissions.deny`, `Edit(/.github/workflows/**)`; [2.1.289](evidence/permission-rules-2.1.289.md), [review 07](reviews/07-v0.7.0.md) on 2.1.291):

- **Blocks:** the Edit and Write tools; redirections, including a here-doc into `>>`; and the commands Claude Code recognises as file commands: `sed -i`, `tee`, `cp`, `rm`, `mv`.
- **Does not block:** any utility or wrapper it does not recognise, for example `sh -c "…"`, `python3`, `perl -pi`, `dd`, `install`, `truncate`, `ln`, `git rm`, `git mv`, `git checkout --`, `find -delete`, `xargs rm`, `git apply`.
- **An `ask` rule** stops only the edit tools, and in `-p` it means deny.

**The deny rule plus the sandbox** (`sandbox.enabled`, `failIfUnavailable`, `allowUnsandboxedCommands: false`, the directory in `filesystem.denyWrite`; [2.1.291, Linux](evidence/sandbox-2.1.291.md)):

- **Blocks:** every working-tree route tried, including all of the above, and an explicit request to run outside the sandbox.
- **Does not block:** a commit. `git checkout HEAD~1 -- <workflow>` failed on the file but staged the old version, and `git commit` committed it. `HEAD` held the weakened workflow while the file on disk still showed the strong one. Git's index lives in `.git`, which a sandboxed agent must be able to write in order to use git at all.

**What qualifies** is review where the agent cannot reach it: required review from code owners for `.github/workflows/` (and any other check configuration), with "Do not allow bypassing the above settings" enabled so administrators cannot skip it, and with the agent holding no credentials that could approve or bypass. Pull request authors cannot approve their own pull requests. This is an Engineer gate (branch protection) enforcing an Administer act (a review), and it earns IPL credit for independence only if the reviewer reads the workflow diff itself rather than the author's summary of it.

**The local guards are still worth having**, as narrow Engineer controls that close the direct routes and leave only a deliberate one:

```json
{
  "permissions": { "deny": ["Edit(/.github/workflows/**)"] },
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "filesystem": { "denyWrite": ["./.github/workflows"] }
  }
}
```

- **The deny rule alone** costs nothing else. It stops the edit tools, which are the route an agent takes first.
- **The sandbox changes the whole session.** Shell commands lose network access except to domains you allow, and can write only inside the project and the temp directory. Sandboxed commands also run without a permission prompt by default (`autoAllowBashIfSandboxed`). Enable it for its own sake, not for this file alone.
- **Rung:** Engineer, interlocks outside the model. Adopting them is opt-in, which is Administer. The next rung up is Eliminate, meaning checks defined and enforced outside the repository the agent works in, which is not available to most projects.
- **Scope:**
  - **Observed.** In project settings, a `/`-anchored permission pattern is relative to the project root, and a session started in a subdirectory does not load the project's `.claude/settings.json` at all. For a user-level rule in `~/.claude/settings.json` that applies everywhere, use `Edit(//**/.github/workflows/**)`; a `**/` pattern does not reach parent directories. The deny rule behaves the same in auto mode.
  - **Documented, not observed here:**
    - `.claude/settings.local.json` loads from the git root since 2.1.211, which covers subdirectory sessions in one repository.
    - Sandbox paths use `./` for project-relative, not `/`. On Linux, sandbox write paths containing wildcards are ignored. The sandbox needs bubblewrap on Linux and does not run on native Windows.
    - Claude Code already guards some files without any rule: `.claude/`, `.pre-commit-config.yaml`, `.husky/`, `lefthook.yml`, `pyrightconfig.json`, `.mcp.json`. Edits to them are prompted in the default and acceptEdits modes, go to the classifier in auto mode, are denied in dontAsk mode and are allowed in bypassPermissions mode.
  - **Sources:** [permissions](https://code.claude.com/docs/en/permissions.md), [permission modes](https://code.claude.com/docs/en/permission-modes.md), [sandboxing](https://code.claude.com/docs/en/sandboxing.md).
- **When to remove them:** when code-owner review guards the files, or when you are the one they keep stopping. A deny rule that keeps getting in the way of legitimate maintenance will be removed under pressure anyway.

## What this does not cover

- **Test files themselves:** skip and xfail markers, loosened assertions, deleted tests. The rules below ask for these to be named; nothing enforces it.
- **Inline suppressions in source:** `# type: ignore`, `# noqa`, `eslint-disable`, `# pragma: no cover`.
- **Generated or mixed files:** `conftest.py`, snapshot files rewritten by a test runner, and check settings inside mixed-purpose files (`pyproject.toml`, `setup.cfg`, `package.json`).
- **Commits through git's index**, under either local guard; see above.
- **Without the sandbox, the deny rule's bypasses**, listed above.
- **Run-time escapes:** `--no-verify`, `SKIP=`, `PYTEST_ADDOPTS`, and `-k`, `--deselect` or `--no-cov` on the command line.
- **Sessions outside the rule's reach:** sessions started in a subdirectory without a user-level rule, and anything in bypassPermissions mode.
- **Interactive sessions and macOS:** all observations are from `-p` on Linux.

## The rules this adds

Two lines in [CLAUDE.md](CLAUDE.md) and the skill, both Administer. They are written as actions that leave evidence in the transcript, not as a list of layers to recite:

- Before saying a change is verified, run the checks that existed before it, unmodified, and report their result apart from tests you wrote.
- Do not weaken or disable a check so that your own change passes unless the task asks for it, and name every check you changed.

In round 7's small behaviour test (Haiku, three runs per arm), neither rule caused harm, and neither had an observable effect: no arm weakened a test, and no arm ran the pre-existing suite separately. See [review 07](reviews/07-v0.7.0.md).
