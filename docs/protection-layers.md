# Independent protection layers

The ladder ranks a control by its mechanism. The [indicators](indicators.md) count how often a control is called on. Neither asks whether the checks standing between an agent's mistake and its consequence deserve to be counted at all. This page takes that question from Layer of Protection Analysis (LOPA), keeps its qualitative half, and is explicit about the half it leaves out.

## The original

LOPA (CCPS, 2001) is semi-quantitative. For one scenario, an initiating event leading to a consequence, it multiplies the event's frequency by each protection layer's probability of failure on demand and compares the result with a tolerable frequency. Only some safeguards earn credit. CCPS's guidelines on initiating events and independent protection layers (2015) list the core attributes an independent protection layer (IPL) must have:

- **Independence**: of the initiating event, and of every other layer credited in the same scenario.
- **Functionality**: it can actually stop this consequence, in time.
- **Integrity**: the risk reduction it can be credited with, as a probability of failure on demand.
- **Reliability**: it works as designed when called on.
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
| Type checker or linter whose configuration the change does not touch | Yes, for the defect classes it covers | The oracle is the language or the rule set. |
| A test checked against captured real output | Yes | The oracle is the system's actual behaviour. This is the typed accessor validated against a fixture in [CLAUDE.md](CLAUDE.md). |
| A spec, acceptance test or review from someone who has not seen the author's framing | Yes | It comes from a different reading. |
| A test the agent wrote from its own understanding, before or after the code | No | The same reading produced the code and the expected answer. Writing the test first catches slips, where the code fails to do what the agent meant; it cannot catch a misreading of what was wanted. |
| The agent's review of its own diff | No | It is the same attention that made the mistake. |
| A second model, or a person, reviewing with the author's description or conversation in view | No | The framing is the common cause. Without it, yes. |
| Any check the change itself edits | No | It fails access security; see below. |

## Common mode: one workflow file

Lint, types and tests usually run from one CI workflow, and one edit to that file silences all three: `|| true`, a deleted job, `continue-on-error`. For independence they are therefore one layer, and the workflow file is the common mode. Branch protection can make a named check required, but a `pull_request` workflow runs from the pull request's own copy of the file. A required check is an IPL only if the workflow file is guarded as well, for example by required review from code owners covering `.github/workflows/`, or by the deny rule below.

## The ladder and IPLs

The rung is a property of a mechanism. IPL status is a property of a mechanism relative to a scenario. The two do not line up:

- An Engineer-rung check can fail as an IPL, for example a test configuration the agent can edit.
- An Administer control can pass, for example a review by someone without the author's framing.

IPL status does not re-rank the ladder, and it is no reason to refuse an Administer fix. Its use is diagnostic. When the protection on a change rests on layers that fail independence, apply the ladder to that: build a check whose oracle is independent (capture real output, take the acceptance test from the spec), or guard the common mode.

## This plugin, honestly

None of the plugin's controls is an IPL:

| Control | IPL? | Why |
|---|---|---|
| Gate | No | Trivial variation such as a trailing comment defeats it, and its state file can be written by the agent it constrains. It is a narrow Engineer control, not a layer. |
| No-op detector | No | It feeds the gate. |
| Reminder | No | It works only if the agent acts on it (Administer). |
| Rules (`SKILL.md`, `CLAUDE.md`) | No | Administer. |
| Indicators | Not protection | They provide auditability for the controls. |

## Access security: deny rules

An agent that can edit a check can switch it off, so scenario 2 needs a control the agent cannot talk its way past. Claude Code's permission rules are enforced outside the model. Against writes to a workflow file, Claude Code 2.1.289 in `-p` was observed to do the following ([evidence](evidence/permission-rules-2.1.289.md)):

| Write | `deny` rule | `ask` rule |
|---|---|---|
| Edit, Write, MultiEdit tools | blocked | blocked in `-p` (nobody to ask) |
| `echo >>`, `sed -i`, `rm`, `mv` | blocked | not blocked by the rule |
| `python3 -c "open(...)"` | **not blocked** | not blocked by the rule |

Use `deny`. An `ask` rule covers only the edit tools, so an agent with Bash can make the same change through the shell. For the project, in `.claude/settings.json`:

```json
{
  "permissions": {
    "deny": ["Edit(/.github/workflows/**)"]
  }
}
```

Add `Edit(...)` entries for the other files your checks live in, chosen deliberately, for example `pytest.ini`, `tox.ini`, `.coveragerc`, `mypy.ini`, `ruff.toml`, `eslint.config.*`. With a deny rule you edit those files yourself. If you routinely have an agent maintain them, a deny rule will be removed under pressure, and required code-owner review is the better guard.

- **Rung:** Engineer, an interlock outside the model. Adopting it is opt-in, which is Administer. The next rung up is Eliminate: checks defined and enforced outside the repository the agent works in. That is not available to most projects.
- **Scope (documented, not observed here):**
  - A `/`-anchored pattern in project settings is relative to the project root.
  - Project settings load from the directory the session starts in, so a session started in a subdirectory does not get them. A user-level rule in `~/.claude/settings.json`, `Edit(**/.github/workflows/**)`, covers every directory.
  - Claude Code already guards some files without any rule: `.claude/`, `.pre-commit-config.yaml`, `.husky/`, `lefthook.yml`, `pyrightconfig.json`, `.mcp.json`. Edits to them are prompted in the default and acceptEdits modes, go to the classifier in auto mode, are denied in dontAsk mode and are allowed in bypassPermissions mode.
  - `sandbox.filesystem.denyWrite` can stop the script case at the OS level, but only with `sandbox.enabled`, and it does not cover the edit tools.
  - See [permissions](https://code.claude.com/docs/en/permissions.md), [permission modes](https://code.claude.com/docs/en/permission-modes.md) and [sandboxing](https://code.claude.com/docs/en/sandboxing.md).
- **When to remove it:** remove the rule when the files it guards are guarded elsewhere (code-owner review, rules enforced outside the repository), or when you are the one it keeps stopping.

## What this does not cover

- **Test files themselves:** skip and xfail markers, loosened assertions, deleted tests. The rules below ask for these to be named; nothing enforces it.
- **Generated or mixed files:** `conftest.py`, snapshot files rewritten by a test runner, and check settings inside mixed-purpose files (`pyproject.toml`, `setup.cfg`, `package.json`).
- **Shell routes:**
  - scripts that open files themselves;
  - `git checkout <ref> -- <file>`, `git stash`;
  - here-docs;
  - `--no-verify`, `SKIP=`, `PYTEST_ADDOPTS`, and `-k`, `--deselect` or `--no-cov` on the command line.
- **Sessions outside the rule's reach:** sessions started outside the directory that holds the project settings, and anything in bypassPermissions mode.
- **The interactive form of all of the above:** only `-p` was observed.

## The rules this adds

Two lines in [CLAUDE.md](CLAUDE.md) and the skill, both Administer. They are written as actions that leave evidence in the transcript, not as a list of layers to recite:

- Before saying a change is verified, run the checks that existed before it, unmodified, and report their result apart from tests you wrote.
- Do not weaken or disable a check so that your own change passes unless the task asks for it, and name every check you changed.
