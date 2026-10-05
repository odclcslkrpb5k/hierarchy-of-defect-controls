#!/usr/bin/env python3
"""
Hierarchy of Defect Controls hooks. One script, five modes, one locked state
file per session with per-agent failure counts.

  gate     PreToolUse (all tools)
           Denies a call identical to one that has failed THRESHOLD times
           with the same error signature and with nothing changed since
           the last failure. Also arms the no-op detector for a simple
           `sed -i` / `perl -pi`.

  failure  PostToolUseFailure (all tools)
           Records the failure by exact call (for the gate) and by error
           signature (for the reminder). On the Nth identical signature
           it injects a factual reminder as additionalContext.

  success  PostToolUse (all tools)
           A call that succeeds clears its own failure count. A successful
           edit tool bumps the edit epoch. If the call was an armed
           `sed -i` / `perl -pi` and its operand files are byte-identical
           afterwards, the call is recorded as a failure.

  reset    UserPromptSubmit
           Clears gate counts for every agent. A new user turn is new
           external state. Reminder signatures are kept.

  fingerprint  Prints the current working-tree fingerprint. Debug aid.

Tier 4 log: when HDC_EVENTS names an absolute path, a swallowed exception
and a corrupt state file each append one JSON line there (no command or
error text). Unset, nothing is written. See docs/indicators.md.

"Nothing changed" is a marker with three parts, any of which reopens the
gate when it changes: a working-tree fingerprint (git plumbing: status,
diff-files, diff-index, so tracked and non-ignored files), the HEAD commit
(so checkout, pull, reset, stash pop), and the edit epoch (so Edit/Write to
gitignored or out-of-repo files). Environment changes made through Bash
(pip install, docker start) change none of the three; the escape there is
a new user message.

The fingerprint uses `git status` plus the plumbing diffs diff-files and
diff-index, all under GIT_OPTIONAL_LOCKS=0. Porcelain `git diff` refreshes
the index and takes .git/index.lock, which made concurrent user commits
fail in v0.2.0.

The fingerprint is computed only when a decision needs it: the gate when
this agent has an armed call for this key or the call arms the no-op
detector; success when a snapshot exists for this tool_use_id; failure
always. It is computed outside the state lock.

The no-op detector hashes the file operands of a simple `sed -i` /
`perl -pi` before and after. It needs no git and handles gitignored,
out-of-repo and non-git targets. Compound commands (unquoted &&, ||, ;,
|, &, newlines) are skipped: the detector cannot tell which part changed
what. Switch clusters are parsed so that `-Ilib` and `-Mstrict` are not
read as `-i`. `git apply` and `patch` are not covered on purpose: a
repeated patch fails, so the gate already handles it.

Everything is best-effort. Any error exits 0 silently so a bug here can
never break a session. The cost is silent always-pass on a broken hook,
which is why test/run_tests.py exists and why its fixtures should be
captured payloads, not reconstructions.
"""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import stat
import tempfile
import time
import traceback

VERSION = "0.6.0"        # keep equal to .claude-plugin/plugin.json
SCHEMA = 1               # HDC_EVENTS record format
THRESHOLD = 2            # identical failures before the reminder and gate act
MAX_FINGERPRINT = 160    # chars of normalised error kept for hashing
GIT_TIMEOUT = 3          # seconds per git call
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
IGNORED_INPUT_FIELDS = {"description"}   # intent, not call
ERRORISH_RE = re.compile(r"error|fail|exception|fatal|traceback|panic|denied|refused", re.I)
DECORATION_RE = re.compile(r"^[\s=\-_*#~+.|/\\<>\u2500-\u257f]*$")
BANNER_RE = re.compile(r"^\s*[=\-_*#~]{3,}\s.*\s[=\-_*#~]{3,}\s*$")   # "=== FAILURES ==="
SKIP_LINES = {"traceback (most recent call last):"}

# Message text the report (scripts/hdc_report.py) parses back out of
# transcripts. Defined once here so the two cannot drift.
DENY_PREFIX = "Blocked by the Hierarchy of Defect Controls gate: "
DENY_RE = re.compile(re.escape(DENY_PREFIX)
                     + r'(?P<desc>.+?) has failed (?P<n>\d+) times with the same error \("(?P<sig>.*?)"\)', re.S)
REMINDER_RE = re.compile(r'^The (?P<tool>\S+) tool has now failed (?P<n>\d+) times in this session '
                         r'with the same signature: "(?P<sig>.*)"\. The Hierarchy', re.S)
NOOP_TEXT = "reported success but its target is byte-identical"
NOOP_RE = re.compile(r"^(?P<desc>.+?) reported success but "
                     r"(?:its target is byte-identical|the working tree is unchanged)", re.S)  # second: <=0.3
NOOP_SIG = "no-op in-place edit: target unchanged"   # "...: working tree unchanged" in <=0.3

try:
    import fcntl  # POSIX only
except ImportError:  # pragma: no cover
    fcntl = None


# ---------------------------------------------------------------- helpers

def normalise_line(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"^e\s+", "", s)                          # pytest "E   " prefix
    s = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<uuid>", s)
    s = re.sub(r"0x[0-9a-f]+", "0x", s)
    s = re.sub(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,}\b", "<hex>", s)   # ids with >=1 digit
    s = re.sub(r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}[:\d.]*z?\b", "<ts>", s)
    s = re.sub(r"/tmp/\S+", "/tmp/<path>", s)
    s = re.sub(r"\b\d+(?:\.\d+)?(ns|us|µs|ms|s|m|h|kb|mb|gb|kib|mib|gib|k|b)\b", r"<n>\1", s)
    s = re.sub(r"\bline \d+", "line <n>", s)
    s = re.sub(r":\d+(:\d+)?\b", ":<n>", s)
    s = re.sub(r"\b\d+\b", "<n>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:MAX_FINGERPRINT]


def is_decoration(ln: str) -> bool:
    return (not ln.strip() or bool(DECORATION_RE.match(ln)) or bool(BANNER_RE.match(ln))
            or ln.strip().lower() in SKIP_LINES)


def error_lines(lines):
    """First and last error-like lines (deduplicated); with no error-like
    line, the first and last non-decoration lines instead. A Python traceback's last line is the exception;
    pytest's first error-like line is its `E   ...` line and its last is
    the FAILED summary naming the test."""
    candidates = [ln for ln in lines if not is_decoration(ln)]
    errorish = [ln for ln in candidates if ERRORISH_RE.search(ln)]
    pool = errorish or candidates
    if not pool:
        return []
    picked = [pool[0]]
    if pool[-1] is not pool[0]:
        picked.append(pool[-1])
    return picked


def error_signature(tool: str, tool_input, text: str) -> str:
    """Stable signature for an error. Bash errors arrive as "Exit code N"
    then output; use the code plus the error-like lines, and for
    output-less failures the command's first word."""
    if not text or not text.strip():
        return ""
    lines = text.strip().splitlines()
    m = re.match(r"\s*exit code\s+(\d+)\s*$", lines[0], re.I)
    if m:
        body = " | ".join(normalise_line(ln) for ln in error_lines(lines[1:]))
        if body:
            return f"exit {m.group(1)}: {body}"[:MAX_FINGERPRINT + 20]
        head = ""
        if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
            head = tool_input["command"].strip().split()[0] if tool_input["command"].strip() else ""
        return f"exit {m.group(1)}: {tool.lower()} {head}".strip()
    return " | ".join(normalise_line(ln) for ln in error_lines(lines))[:MAX_FINGERPRINT + 20]


def canonical_call(tool: str, tool_input) -> str:
    if isinstance(tool_input, dict):
        tool_input = {k: v for k, v in tool_input.items() if k not in IGNORED_INPUT_FIELDS}
    body = json.dumps(tool_input, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(f"{tool}\n{body}".encode("utf-8")).hexdigest()[:16]


def extract_error(payload: dict) -> str:
    for key in ("error", "tool_response", "result", "output"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, dict):
            for sub in ("error", "message", "stderr", "stdout"):
                if isinstance(val.get(sub), str) and val[sub].strip():
                    return val[sub]
    return ""


def describe_call(tool: str, tool_input) -> str:
    if isinstance(tool_input, dict):
        for k in ("command", "file_path", "path", "url", "query", "pattern"):
            if isinstance(tool_input.get(k), str):
                v = re.sub(r"\s+", " ", tool_input[k]).strip()
                return f"{tool}({v[:120]})"
    return tool


def agent_key(payload: dict) -> str:
    return str(payload.get("agent_id") or "main")


# ------------------------------------------------------ no-op detection

def file_hash(path: str):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()
    except OSError:
        return None


# perl switches that take an argument; anything after them in a cluster is
# the argument. `i` takes an optional backup suffix, so `-pi`, `-i.bak`,
# `-pi.orig` are in-place and `-Ilib`, `-Mstrict`, `-e` are not.
PERL_ARG_SWITCHES = set("CdDeEFImMxV")
PERL_OPT_OCTAL = set("0l")          # consume trailing digits only
SED_ARG_SWITCHES = set("efl")


def perl_inplace(tok: str) -> bool:
    if not tok.startswith("-") or tok.startswith("--"):
        return False
    body = tok[1:]
    k = 0
    while k < len(body):
        c = body[k]
        if c == "i":
            return True
        if c in PERL_ARG_SWITCHES:
            return False
        if c in PERL_OPT_OCTAL:
            k += 1
            while k < len(body) and body[k].isdigit():
                k += 1
            continue
        k += 1
    return False


def sed_inplace(tok: str) -> bool:
    if tok.startswith("--in-place"):
        return True
    if not tok.startswith("-") or tok.startswith("--"):
        return False
    for c in tok[1:]:
        if c == "i":
            return True
        if c in SED_ARG_SWITCHES:
            return False
    return False


def tokenise(cmd: str):
    """(tokens, is_compound). Uses shlex punctuation tokens so `|` or `;`
    inside a quoted sed script do not count as compound."""
    if "\n" in cmd:
        return None, True
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return None, True
    compound = any(t in ("&&", "||", ";", "|", "&") for t in toks)
    return toks, compound


def resolve(path: str, cwd: str) -> str:
    return path if os.path.isabs(path) else os.path.join(cwd, path)


def noop_plan(tool: str, tool_input, cwd: str):
    """Decide how to check a command for a silent no-op.

    Returns ("files", {path: hash}) for a simple `sed -i` / `perl -pi`
    with resolvable file operands, else None. `git apply` and `patch` are
    deliberately not handled: re-applying an applied patch exits non-zero
    in every form tested, so the failure path and the gate already cover
    that loop, and the only patch that succeeds without changing anything
    is an empty one. A parser for patch targets produced a new class of
    false reports in three consecutive reviews; removing it is the
    Eliminate fix."""
    if tool != "Bash" or not isinstance(tool_input, dict):
        return None
    cmd = tool_input.get("command")
    if not isinstance(cmd, str):
        return None
    toks, compound = tokenise(cmd)
    if compound or not toks:
        return None
    head = toks[0]
    if head in ("sed", "perl"):
        check = sed_inplace if head == "sed" else perl_inplace
        if not any(check(t) for t in toks[1:]):
            return None
        hashes = {}
        skip_next = False
        for t in toks[1:]:
            if skip_next:
                skip_next = False
                continue
            if t in ("-e", "-f", "-l", "-M", "-I", "-E", "-C", "-x", "-F"):
                skip_next = True
                continue
            if t.startswith("-"):
                continue
            p = resolve(t, cwd)
            if os.path.isfile(p):
                h = file_hash(p)
                if h:
                    hashes[p] = h
        return ("files", hashes) if hashes else None
    return None


# --------------------------------------------------------- working tree

def _git(args, cwd):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    log = os.environ.get("HDC_GIT_LOG")
    if log:
        try:
            with open(log, "a") as fh:
                fh.write(" ".join(args) + "\n")
        except OSError:
            pass
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                          timeout=GIT_TIMEOUT, check=False, env=env)


def tree_state(cwd: str):
    """(fingerprint, head) using plumbing only, or (None, None) outside git.

    diff-files and diff-index do not refresh the index, so they never take
    index.lock; porcelain `git diff` does."""
    try:
        top = _git(["rev-parse", "--show-toplevel"], cwd)
        if top.returncode != 0:
            return None, None
        root = top.stdout.decode("utf-8", "replace").strip()
        headp = _git(["rev-parse", "--verify", "-q", "HEAD"], root)
        head = headp.stdout.decode().strip() if headp.returncode == 0 else "unborn"
        h = hashlib.sha1()
        status = _git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], root)
        if status.returncode != 0:
            return None, None
        h.update(status.stdout)
        for entry in status.stdout.split(b"\0"):
            if entry.startswith(b"?? "):
                rel = entry[3:].decode("utf-8", "replace")
                try:
                    st = os.stat(os.path.join(root, rel))
                    h.update(f"{rel}:{st.st_mtime_ns}:{st.st_size}".encode())
                except OSError:
                    pass
        d1 = _git(["diff-files", "-p"], root)
        if d1.returncode != 0:
            return None, None
        h.update(d1.stdout)
        base = head if head != "unborn" else EMPTY_TREE
        d2 = _git(["diff-index", "-p", "--cached", base], root)
        if d2.returncode != 0:
            return None, None
        h.update(d2.stdout)
        return h.hexdigest(), head
    except (OSError, subprocess.SubprocessError):
        return None, None


def marker_for(payload: dict, edit_epoch: int, tree=None) -> str:
    """Three-part marker. `tree` may be passed in when already computed."""
    if tree is None:
        tree = tree_state(payload.get("cwd") or os.getcwd())
    fp, head = tree
    return f"git:{fp}:{head}:e{edit_epoch}" if fp else f"nogit:e{edit_epoch}"


# ----------------------------------------------------------- tier 4 log

MAX_EVENT = 4096         # bytes per record; one os.write, so appends do not interleave


def log_event(kind: str, session_id=None, **fields) -> None:
    """Append one Tier 4 record to $HDC_EVENTS. Opt-in, best-effort, and
    never able to block: the path must be absolute and a regular file (or
    not exist yet), and the open is non-blocking, so a FIFO or a stale
    mount cannot hold a hook until its timeout."""
    path = os.environ.get("HDC_EVENTS")
    if not path:
        return
    try:
        if not os.path.isabs(path):
            return
        try:
            if not stat.S_ISREG(os.stat(path).st_mode):
                return
        except FileNotFoundError:
            pass
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "schema": SCHEMA,
               "version": VERSION, "threshold": THRESHOLD, "kind": kind,
               "session_id": str(session_id or "unknown")}
        rec.update(fields)
        line = (json.dumps(rec, separators=(",", ":")) + "\n").encode("utf-8")
        if len(line) > MAX_EVENT:
            return
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ state

def state_path(payload: dict) -> str:
    base = payload.get("scratchpad_dir") or tempfile.gettempdir()
    sid = payload.get("session_id") or "unknown"
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sid)
    return os.path.join(base, f"hdc-state-{safe}.json")


def _fresh():
    return {"edit_epoch": 0, "agents": {}, "pending": {}}


def _sid_of(path: str) -> str:
    name = os.path.basename(path)
    return name[len("hdc-state-"):-len(".json")] if name.startswith("hdc-state-") else name


def peek_state(path: str) -> dict:
    """Unlocked read. Writers replace the file atomically, so a reader sees
    a complete file; it may be a moment stale, which the callers tolerate."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for k, v in _fresh().items():
                data.setdefault(k, v)
            return data
        log_event("state_corrupt", _sid_of(path))
    except ValueError:
        log_event("state_corrupt", _sid_of(path))
    except OSError:
        pass
    return _fresh()


def agent_of(data: dict, key: str) -> dict:
    a = data["agents"].setdefault(key, {})
    a.setdefault("calls", {})        # call_key -> {desc, count, sig, marker}
    a.setdefault("signatures", {})   # sig_key -> {tool, sig, count}
    return a


class State:
    """Locked load-modify-save."""

    def __init__(self, path: str):
        self.path = path
        self.lock_fh = None
        self.data = None

    def __enter__(self):
        if fcntl is not None:
            self.lock_fh = open(self.path + ".lock", "a+")
            fcntl.flock(self.lock_fh, fcntl.LOCK_EX)
        self.data = peek_state(self.path)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                tmp = f"{self.path}.{os.getpid()}.tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self.data, fh)
                os.replace(tmp, self.path)
        finally:
            if self.lock_fh is not None:
                try:
                    fcntl.flock(self.lock_fh, fcntl.LOCK_UN)
                finally:
                    self.lock_fh.close()
        return False


def emit(obj) -> None:
    sys.stdout.write(json.dumps(obj))


# ------------------------------------------------------------------ modes

def reminder_text(tool: str, sig: str, count: int) -> str:
    return (
        f"The {tool} tool has now failed {count} times in this session with "
        f"the same signature: \"{sig}\". The Hierarchy of Defect Controls "
        "applies to repeated in-session mistakes. A resolution to be more "
        "careful is an Administer-rung remedy addressed to the attention "
        "that just failed. The remedy chosen for this failure should be "
        "named by rung (Eliminate, Substitute, Engineer, Administer, "
        "Protect), with the next rung up and the reason it was not taken. "
        "An Engineer control specific to this pattern that can be built "
        "now, or an Eliminate change that removes the place the mistake "
        "happens, is preferred."
    )


def record_failure(data: dict, payload: dict, sig: str, desc: str, marker: str):
    tool = str(payload.get("tool_name") or "unknown")
    tool_input = payload.get("tool_input", {})
    a = agent_of(data, agent_key(payload))
    ck = canonical_call(tool, tool_input)
    call = a["calls"].get(ck) or {"desc": desc, "count": 0, "sig": None}
    call["count"] = int(call.get("count", 0)) + 1 if call.get("sig") == sig else 1
    call["sig"] = sig
    call["marker"] = marker
    a["calls"][ck] = call
    entry = None
    if sig:
        sk = hashlib.sha1(f"{tool}\n{sig}".encode("utf-8")).hexdigest()[:16]
        entry = a["signatures"].get(sk) or {"tool": tool, "sig": sig, "count": 0}
        entry["count"] = int(entry.get("count", 0)) + 1
        a["signatures"][sk] = entry
    return entry, call


def mode_gate(payload: dict) -> None:
    tool = str(payload.get("tool_name") or "unknown")
    tool_input = payload.get("tool_input", {})
    cwd = payload.get("cwd") or os.getcwd()
    path = state_path(payload)
    tuid = payload.get("tool_use_id")
    ck = canonical_call(tool, tool_input)

    # Cheap unlocked look to decide whether any git work is needed (R4).
    snap = peek_state(path)
    call = agent_of(snap, agent_key(payload))["calls"].get(ck)
    armed = bool(call) and int(call.get("count", 0)) >= THRESHOLD
    plan = noop_plan(tool, tool_input, cwd) if tuid else None
    if not armed and plan is None:
        return

    tree = tree_state(cwd) if armed else None

    with State(path) as st:
        if plan is not None:
            st.data["pending"][str(tuid)] = {"kind": "files", "hashes": plan[1]}
        if not armed:
            return
        call = agent_of(st.data, agent_key(payload))["calls"].get(ck)
        if not call or int(call.get("count", 0)) < THRESHOLD:
            return
        if call.get("marker") != marker_for(payload, st.data["edit_epoch"], tree):
            return

    reason = (
        f"{DENY_PREFIX}{call['desc']} has "
        f"failed {call['count']} times with the same error "
        f"(\"{call.get('sig') or 'unknown'}\") and nothing has changed since "
        "the last failure: no file edit, no working-tree change, no new "
        "commit. Re-running an unchanged call after identical failures is the "
        "loop this gate exists to stop. Changing the code, the input, or the "
        "approach reopens it, and so does a new message from the user, which "
        "is the path when the fix happened outside this session (an "
        "environment change, a service restart). The change should be named "
        "by rung (Eliminate, Substitute, Engineer, Administer, Protect)."
    )
    emit({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                 "permissionDecision": "deny",
                                 "permissionDecisionReason": reason}})


def mode_failure(payload: dict) -> None:
    tool = str(payload.get("tool_name") or "unknown")
    tool_input = payload.get("tool_input", {})
    sig = error_signature(tool, tool_input, extract_error(payload))
    tree = tree_state(payload.get("cwd") or os.getcwd())   # outside the lock
    out = None
    with State(state_path(payload)) as st:
        st.data["pending"].pop(str(payload.get("tool_use_id")), None)
        marker = marker_for(payload, st.data["edit_epoch"], tree)
        entry, _ = record_failure(st.data, payload, sig, describe_call(tool, tool_input), marker)
        if entry and entry["count"] >= THRESHOLD:
            out = {"hookSpecificOutput": {"hookEventName": "PostToolUseFailure",
                                          "additionalContext": reminder_text(tool, sig, entry["count"])}}
    if out:
        emit(out)


def mode_success(payload: dict) -> None:
    tool = str(payload.get("tool_name") or "unknown")
    tool_input = payload.get("tool_input", {})
    cwd = payload.get("cwd") or os.getcwd()
    path = state_path(payload)
    tuid = str(payload.get("tool_use_id"))

    tree = None
    out = None
    with State(path) as st:
        pending = st.data["pending"].pop(tuid, None)
        if tool in EDIT_TOOLS:
            st.data["edit_epoch"] = int(st.data["edit_epoch"]) + 1
        noop = False
        if pending and pending.get("kind") == "files":
            before = pending.get("hashes") or {}
            noop = bool(before) and all(file_hash(p) == h for p, h in before.items())
        ck = canonical_call(tool, tool_input)
        if noop:
            marker = marker_for(payload, st.data["edit_epoch"], tree)
            sig = NOOP_SIG
            _, call = record_failure(st.data, payload, sig, describe_call(tool, tool_input), marker)
            out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": (
                f"{call['desc']} {NOOP_TEXT} afterwards: the replacement matched nothing. Recorded as failure "
                f"{call['count']} of this call.")}}
        else:
            agent_of(st.data, agent_key(payload))["calls"].pop(ck, None)
    if out:
        emit(out)


def mode_reset(payload: dict) -> None:
    with State(state_path(payload)) as st:
        for a in st.data["agents"].values():
            a["calls"] = {}
        st.data["pending"] = {}


def mode_fingerprint(payload: dict) -> None:
    fp, head = tree_state(payload.get("cwd") or os.getcwd())
    sys.stdout.write(f"{fp or 'none'} {head or 'none'}\n")


MODES = {"gate": mode_gate, "failure": mode_failure, "success": mode_success,
         "reset": mode_reset, "fingerprint": mode_fingerprint}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = {}
    try:
        fn = MODES.get(mode)
        if fn is None:
            return 0
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if isinstance(payload, dict):
            fn(payload)
    except Exception as exc:  # noqa: BLE001
        # Still exit 0 and say nothing to the session; the record is the
        # only trace. Innermost frame in this file, not in the stdlib.
        here = [f for f in traceback.extract_tb(exc.__traceback__)
                if os.path.abspath(f.filename) == os.path.abspath(__file__)]
        log_event("hook_exception", payload.get("session_id") if isinstance(payload, dict) else None,
                  mode=mode, exc_type=type(exc).__name__,
                  func=here[-1].name if here else None, lineno=here[-1].lineno if here else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
