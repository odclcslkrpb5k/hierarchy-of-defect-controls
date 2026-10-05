#!/usr/bin/env python3
"""
Hierarchy of Defect Controls indicators, an analog of API RP 754. Read-only.

  python3 scripts/hdc_report.py [--all | --project DIR] [--since YYYY-MM-DD] [--json]

Tier 3 (challenges to the controls) and exposure come from Claude Code's
session transcripts, which already record every gate deny (a tool_result)
and every reminder and no-op report (a hook_additional_context attachment).
Tier 4 (the controls themselves impaired) comes from the opt-in HDC_EVENTS
log the hooks write. Tiers 1 and 2 are definitions only; see
docs/indicators.md for the tiers, the counting rules and what none of this
can tell you.

This is a CLI, not a hook mode: it does not read stdin, and it fails loudly.
A report that printed nothing on a bug would read as "no events".
"""

import argparse
import glob
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hdc_hooks import (DENY_PREFIX, DENY_RE, IGNORED_INPUT_FIELDS,  # noqa: E402
                       NOOP_RE, NOOP_SIG, REMINDER_RE)

NOOP_SIG_HEAD = NOOP_SIG.split(":")[0] + ":"   # stable across versions
# Claude Code 2.1.289 wraps a PreToolUse deny reason as "PreToolUse:Bash hook
# error: <reason>"; 2.1.270 stored the reason bare. Accept both.
HOOK_ERROR_WRAPPER = re.compile(r"^[A-Za-z]+:\S+ hook error: ")
MIN_RATE_N = 20          # below this many episodes a rate is noise; print counts only


# ------------------------------------------------------------- locating

def config_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def encode_project(path: str) -> str:
    """Claude Code's transcript directory name for a working directory."""
    return re.sub(r"[^A-Za-z0-9-]", "-", os.path.abspath(path))


def transcripts(project_dir: str):
    """(path, is_subagent) for every transcript in one project directory."""
    for p in sorted(glob.glob(os.path.join(project_dir, "*.jsonl"))):
        yield p, False
    for p in sorted(glob.glob(os.path.join(project_dir, "*", "subagents", "*.jsonl"))):
        yield p, True


# ------------------------------------------------------------- scanning

def call_key(name, tool_input) -> str:
    if isinstance(tool_input, dict):
        tool_input = {k: v for k, v in tool_input.items() if k not in IGNORED_INPUT_FIELDS}
    return f"{name}\n{json.dumps(tool_input, sort_keys=True, separators=(',', ':'))}"


def result_text(block) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


# User-typed entries that are not typed prompts: background-task
# notifications and slash-command bookkeeping. Treating them as turns would
# split episodes; when unsure, merging is the conservative error.
NOT_PROMPT_PREFIXES = ("<task-notification>", "<local-command-", "<command-name>", "<command-message>")


def is_prompt(entry) -> bool:
    """A real user turn, the thing that fires UserPromptSubmit and resets
    the gate. Inferred: tool results, meta entries, compaction summaries and
    the NOT_PROMPT_PREFIXES entries are not turns."""
    if entry.get("isMeta") or entry.get("isCompactSummary"):
        return False
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return False
    c = msg.get("content")
    if isinstance(c, str):
        return bool(c.strip()) and not c.lstrip().startswith(NOT_PROMPT_PREFIXES)
    if isinstance(c, list):
        return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
    return False


def scan(path: str, since=None) -> dict:
    """Counts for one transcript. Events are grouped into episodes: one
    loop (same signature, or same call for a no-op) within one user turn."""
    out = {"tool_calls": 0, "tool_errors": 0, "denies": 0, "reminders": 0, "noops": 0,
           "cleared_by_user": 0, "malformed": 0, "episodes": {}, "seen": False}
    uses = {}            # tool_use_id -> call key
    denied = {}          # call key -> turn of its last deny
    turn = 0

    def event(kind, key):
        ep = out["episodes"].setdefault(f"{turn}\0{key}", {"events": 0, "denies": 0})
        ep["events"] += 1
        if kind == "deny":
            ep["denies"] += 1

    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except ValueError:
                out["malformed"] += 1
                continue
            if not isinstance(e, dict):
                out["malformed"] += 1
                continue
            ts = e.get("timestamp")
            if since and isinstance(ts, str) and ts < since:
                continue
            kind = e.get("type")
            msg = e.get("message") if isinstance(e.get("message"), dict) else {}
            content = msg.get("content")
            if kind == "assistant" and isinstance(content, list):
                out["seen"] = True
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        out["tool_calls"] += 1
                        k = call_key(b.get("name"), b.get("input"))
                        uses[b.get("id")] = k
                        if k in denied and denied[k] < turn:
                            out["cleared_by_user"] += 1
                            del denied[k]
            elif kind == "user":
                if is_prompt(e):
                    turn += 1
                    continue
                for b in content if isinstance(content, list) else []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                        continue
                    if b.get("is_error"):
                        out["tool_errors"] += 1
                    # A deny is an error result. Without is_error, a command
                    # that merely prints a deny message would count as one.
                    text = HOOK_ERROR_WRAPPER.sub("", result_text(b), count=1)
                    if not (b.get("is_error") and text.startswith(DENY_PREFIX)):
                        continue
                    out["denies"] += 1
                    m = DENY_RE.match(text)
                    sig, desc = (m.group("sig"), m.group("desc")) if m else ("", "")
                    event("deny", f"noop\0{desc}" if sig.startswith(NOOP_SIG_HEAD) else f"sig\0{sig}")
                    k = uses.get(b.get("tool_use_id"))
                    if k:
                        denied[k] = turn
            elif kind == "attachment":
                att = e.get("attachment")
                if not (isinstance(att, dict) and att.get("type") == "hook_additional_context"):
                    continue
                texts = att.get("content")
                for t in texts if isinstance(texts, list) else [texts]:
                    if not isinstance(t, str):
                        continue
                    m = REMINDER_RE.match(t)
                    if m:
                        out["reminders"] += 1
                        event("reminder", f"sig\0{m.group('sig')}")
                        continue
                    m = NOOP_RE.match(t)
                    if m:
                        out["noops"] += 1
                        event("noop", f"noop\0{m.group('desc')}")
    return out


# ---------------------------------------------------------------- stats

def poisson_cdf(k: int, mu: float) -> float:
    if mu <= 0:
        return 1.0
    return min(1.0, sum(math.exp(i * math.log(mu) - mu - math.lgamma(i + 1)) for i in range(k + 1)))


def poisson_ci(n: int, alpha: float = 0.05):
    """Exact (Garwood) interval for a Poisson count, by bisection."""
    def solve(f, lo, hi):
        for _ in range(200):
            mid = (lo + hi) / 2
            if f(mid):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    hi_bound = n + 20 * math.sqrt(n + 1) + 20
    lower = 0.0 if n == 0 else solve(lambda mu: 1 - poisson_cdf(n - 1, mu) < alpha / 2, 0.0, hi_bound)
    upper = solve(lambda mu: poisson_cdf(n, mu) > alpha / 2, 0.0, hi_bound)
    return lower, upper


# --------------------------------------------------------------- tier 4

def read_events(path: str, since=None) -> dict:
    out = {"path": path, "records": 0, "malformed": 0, "by_kind": {}, "versions": {}}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                out["malformed"] += 1
                continue
            if not isinstance(r, dict) or (since and str(r.get("ts", "")) < since):
                continue
            out["records"] += 1
            k = str(r.get("kind"))
            out["by_kind"][k] = out["by_kind"].get(k, 0) + 1
            v = str(r.get("version"))
            out["versions"][v] = out["versions"].get(v, 0) + 1
    return out


# --------------------------------------------------------------- report

def build(project_dirs, since=None, events_path=None) -> dict:
    r = {"projects": len(project_dirs), "sessions": 0, "subagents": 0, "tool_calls": 0,
         "tool_errors": 0, "denies": 0, "reminders": 0, "noops": 0, "cleared_by_user": 0,
         "malformed": 0, "episodes": 0, "max_depth": 0, "past_gate": 0}
    for d in project_dirs:
        for path, sub in transcripts(d):
            s = scan(path, since)
            r["malformed"] += s["malformed"]
            if not s["seen"]:
                continue
            r["subagents" if sub else "sessions"] += 1
            for k in ("tool_calls", "tool_errors", "denies", "reminders", "noops", "cleared_by_user"):
                r[k] += s[k]
            for ep in s["episodes"].values():
                r["episodes"] += 1
                r["max_depth"] = max(r["max_depth"], ep["events"])
                r["past_gate"] += ep["denies"] >= 2
    n, calls = r["episodes"], r["tool_calls"]
    if n >= MIN_RATE_N and calls:
        lo, hi = poisson_ci(n)
        r["rate_per_1000"] = {"value": 1000 * n / calls, "ci95": [1000 * lo / calls, 1000 * hi / calls]}
    else:
        r["rate_per_1000"] = None
    r["tier4"] = read_events(events_path, since) if events_path else None
    return r


def render(r, label, since) -> str:
    L = [f"HDC indicators: {label}" + (f", since {since}" if since else "")]
    L.append(f"Observed: {r['sessions']} sessions, {r['subagents']} subagent transcripts, "
             f"{r['tool_calls']:,} tool calls ({r['tool_errors']:,} errors)")
    if r["malformed"]:
        L.append(f"Malformed transcript lines skipped: {r['malformed']}")
    L.append("")
    L.append("Tier 3, challenges to the controls")
    L.append(f"  gate denies                    {r['denies']}")
    L.append(f"  reminders                      {r['reminders']}")
    L.append(f"  no-op edits detected           {r['noops']}")
    L.append(f"  episodes                       {r['episodes']}  (max depth {r['max_depth']}, "
             f"continued past the gate {r['past_gate']})")
    rate = r["rate_per_1000"]
    if rate:
        L.append(f"  episodes per 1,000 tool calls  {rate['value']:.3f}  "
                 f"(95% CI {rate['ci95'][0]:.3f} to {rate['ci95'][1]:.3f})")
    else:
        L.append(f"  episodes per 1,000 tool calls  N<{MIN_RATE_N}, no rate")
    L.append(f"  denies cleared by a user turn  {r['cleared_by_user']}  (the gate's cost in human messages)")
    L.append("")
    t4 = r["tier4"]
    if t4 is None:
        L.append("Tier 4, controls impaired: HDC_EVENTS not set, not observed")
    else:
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(t4["by_kind"].items())) or "none"
        L.append(f"Tier 4, controls impaired ({t4['path']}): {t4['records']} records: {kinds}")
        if len(t4["versions"]) > 1:
            L.append(f"  records span plugin versions {', '.join(sorted(t4['versions']))}; "
                     "do not compare across them")
        if t4["malformed"]:
            L.append(f"  malformed lines skipped: {t4['malformed']}")
        L.append("  Zero is not evidence of health: most degradations are not logged.")
    L.append("")
    L.append("Tiers 1 and 2 are not measured. See docs/indicators.md.")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Hierarchy of Defect Controls indicators (RP 754 analog)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="every project, not just the current one")
    g.add_argument("--project", help="working directory whose transcripts to read (default: cwd)")
    ap.add_argument("--projects-dir", help="transcript root (default: $CLAUDE_CONFIG_DIR/projects)")
    ap.add_argument("--since", help="only entries on or after this date, YYYY-MM-DD")
    ap.add_argument("--events", help="Tier 4 log (default: $HDC_EVENTS)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    if a.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.since):
        ap.error("--since takes YYYY-MM-DD")
    root = a.projects_dir or os.path.join(config_dir(), "projects")
    if not os.path.isdir(root):
        print(f"hdc_report: no transcript directory at {root}", file=sys.stderr)
        return 2
    if a.all:
        dirs = sorted(p for p in glob.glob(os.path.join(root, "*")) if os.path.isdir(p))
        label = f"all {len(dirs)} projects"
    else:
        proj = a.project or os.getcwd()
        d = os.path.join(root, encode_project(proj))
        if not os.path.isdir(d):
            print(f"hdc_report: no transcripts for {proj} (looked for {d}); try --all", file=sys.stderr)
            return 2
        dirs, label = [d], os.path.abspath(proj)

    r = build(dirs, a.since, a.events or os.environ.get("HDC_EVENTS"))
    print(json.dumps(r, indent=2) if a.json else render(r, label, a.since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
