#!/usr/bin/env python3
"""
Tests for scripts/hdc_hooks.py. Run: python3 test/run_tests.py

Payloads are built from test/fixtures/*.json (see fixtures/README.md for
provenance). Each test simulates a tool call the way Claude Code does:
PreToolUse `gate` -> the real command runs -> `success` or `failure`.
Prefixes in test names (r4_, r5_) refer to the retest checklist of that
review round; bare numbers refer to round 2.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "scripts", "hdc_hooks.py")
FIX = os.path.join(HERE, "fixtures")
PY = sys.executable

_n = [0]


def fixture(name):
    with open(os.path.join(FIX, name + ".json")) as fh:
        return json.load(fh)


def hook(mode, payload, env=None):
    r = subprocess.run([PY, SCRIPT, mode], input=json.dumps(payload), capture_output=True,
                       text=True, check=False, env=env or os.environ)
    return r.stdout


def denied(out):
    return '"permissionDecision": "deny"' in out


class Session:
    """One fake session in one directory."""

    def __init__(self, cwd, scratch):
        self.cwd, self.scratch = cwd, scratch
        self.sid = "s-" + os.path.basename(scratch)

    def base(self, name, **kw):
        p = fixture(name)
        p.update({"session_id": self.sid, "cwd": self.cwd, "scratchpad_dir": self.scratch})
        p.update(kw)
        return p

    def pre(self, cmd, agent=None, tool="Bash", tool_input=None, extra=None):
        _n[0] += 1
        ti = tool_input if tool_input is not None else {"command": cmd, "description": f"step {_n[0]}"}
        if extra:
            ti.update(extra)
        p = self.base("pre_tool_use_subagent" if agent else "pre_tool_use",
                      tool_name=tool, tool_input=ti, tool_use_id=f"toolu_{_n[0]}")
        if agent:
            p["agent_id"] = agent
        return p

    def run_bash(self, cmd, agent=None, extra=None):
        """gate -> real command -> success/failure. Returns (status, context)."""
        p = self.pre(cmd, agent=agent, extra=extra)
        if denied(hook("gate", p)):
            return "DENIED", ""
        res = subprocess.run(cmd, shell=True, cwd=self.cwd, capture_output=True, text=True)
        common = {k: p[k] for k in ("tool_name", "tool_input", "tool_use_id")}
        if agent:
            common["agent_id"] = agent
        if res.returncode == 0:
            out = hook("success", self.base("post_tool_use", **common,
                       tool_response={"stdout": res.stdout, "stderr": res.stderr, "interrupted": False}))
        else:
            out = hook("failure", self.base("post_tool_use_failure", **common,
                       error=f"Exit code {res.returncode}\n{res.stdout}{res.stderr}".strip()))
        ctx = json.loads(out)["hookSpecificOutput"].get("additionalContext", "") if out else ""
        return f"exit={res.returncode}", ctx

    def fake_fail(self, cmd, err, agent=None, extra=None):
        """Record a failure without running anything."""
        p = self.pre(cmd, agent=agent, extra=extra)
        hook("gate", p)
        common = {k: p[k] for k in ("tool_name", "tool_input", "tool_use_id")}
        if agent:
            common["agent_id"] = agent
        return hook("failure", self.base("post_tool_use_failure", **common, error=err))

    def edit_tool(self, path, old, new):
        """Simulate the Edit tool: gate, write, success."""
        ti = {"file_path": path, "old_string": old, "new_string": new, "replace_all": False}
        p = self.pre(None, tool="Edit", tool_input=ti)
        hook("gate", p)
        with open(path) as fh:
            s = fh.read()
        with open(path, "w") as fh:
            fh.write(s.replace(old, new))
        return hook("success", self.base("post_tool_use_edit", tool_input=ti,
                                         tool_use_id=p["tool_use_id"], tool_response={"filePath": path}))

    def reset(self):
        return hook("reset", self.base("user_prompt_submit"))

    def gate(self, cmd, agent=None, extra=None):
        return denied(hook("gate", self.pre(cmd, agent=agent, extra=extra)))


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


class Base(unittest.TestCase):
    use_git = True

    def setUp(self):
        self.scratch = tempfile.mkdtemp(prefix="hdc-scratch-")
        self.dir = tempfile.mkdtemp(prefix="hdc-repo-" if self.use_git else "hdc-nogit-")
        if self.use_git:
            git(self.dir, "init", "-q", "-b", "main")
            git(self.dir, "config", "user.email", "t@t")
            git(self.dir, "config", "user.name", "t")
            self.write("x.txt", "foo\n")
            self.write(".gitignore", ".env\n")
            git(self.dir, "add", "-A")
            git(self.dir, "commit", "-qm", "init")
        self.s = Session(self.dir, self.scratch)

    def tearDown(self):
        shutil.rmtree(self.scratch, ignore_errors=True)
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, rel, content):
        with open(os.path.join(self.dir, rel), "w") as fh:
            fh.write(content)

    def read(self, rel):
        with open(os.path.join(self.dir, rel)) as fh:
            return fh.read()

    def arm(self, cmd="sh t.sh"):
        self.write("t.sh", "exit 1\n")
        self.s.run_bash(cmd)
        self.s.run_bash(cmd)


# ---------------------------------------------------------------- gate

class GateCore(Base):
    def test_blocks_third_identical_failure(self):
        self.arm()
        self.assertEqual(self.s.run_bash("sh t.sh"), ("DENIED", ""))

    def test_reminder_wording_has_no_verdict_on_previous_remedy(self):
        self.arm()
        self.write("t.sh", "exit 1\n")
        # a new failure after reset should not accuse the model
        self.s.reset()
        _, ctx = self.s.run_bash("sh t.sh")
        self.assertIn("failed 3 times", ctx)
        self.assertNotIn("too low on the ladder", ctx)

    def test_success_clears(self):
        self.arm()
        self.write("t.sh", "exit 0\n")
        self.assertEqual(self.s.run_bash("sh t.sh")[0], "exit=0")  # tree changed -> allowed
        self.write("t.sh", "exit 1\n")
        self.assertEqual(self.s.run_bash("sh t.sh")[0], "exit=1")  # count restarted

    def test_timeout_and_background_are_changes(self):
        self.s.fake_fail("pytest", "Exit code 1\nFAILED a")
        self.s.fake_fail("pytest", "Exit code 1\nFAILED a")
        self.assertTrue(self.s.gate("pytest"))
        self.assertFalse(self.s.gate("pytest", extra={"timeout": 600000}))
        self.assertFalse(self.s.gate("pytest", extra={"run_in_background": True}))

    def test_whitespace_fix_is_a_change(self):
        bad = "python3 - <<'PY'\nfor i in range(2):\nprint(i)\nPY"
        good = "python3 - <<'PY'\nfor i in range(2):\n    print(i)\nPY"
        self.s.run_bash(bad)
        self.s.run_bash(bad)
        self.assertEqual(self.s.run_bash(bad)[0], "DENIED")
        self.assertEqual(self.s.run_bash(good)[0], "exit=0")

    def test_14_reset_via_user_prompt(self):
        self.arm()
        self.assertTrue(self.s.gate("sh t.sh"))
        self.s.reset()
        self.assertFalse(self.s.gate("sh t.sh"))

    def test_14_subagent_isolation(self):
        self.arm()
        self.assertTrue(self.s.gate("sh t.sh"))
        self.assertFalse(self.s.gate("sh t.sh", agent="agent_7"))
        self.s.run_bash("sh t.sh", agent="agent_7")
        self.s.run_bash("sh t.sh", agent="agent_7")
        self.assertTrue(self.s.gate("sh t.sh", agent="agent_7"))


# ----------------------------------------------------- reopening (R3)

class Reopen(Base):
    def test_8_edit_tool_on_gitignored_file_reopens(self):
        self.write(".env", "BAD\n")
        self.write("check.py", "import sys; sys.exit(0 if open('.env').read().strip()=='OK' else 3)\n")
        git(self.dir, "add", "check.py")
        git(self.dir, "commit", "-qm", "c")
        self.s.run_bash("python3 check.py")
        self.s.run_bash("python3 check.py")
        self.assertTrue(self.s.gate("python3 check.py"))
        self.s.edit_tool(os.path.join(self.dir, ".env"), "BAD", "OK")
        self.assertEqual(self.s.run_bash("python3 check.py")[0], "exit=0")

    def test_9_git_checkout_on_clean_tree_reopens(self):
        self.write("t.sh", "exit 1\n")
        git(self.dir, "add", "t.sh")
        git(self.dir, "commit", "-qm", "broken")
        git(self.dir, "checkout", "-qb", "fix")
        self.write("t.sh", "exit 0\n")
        git(self.dir, "commit", "-qam", "fixed")
        git(self.dir, "checkout", "-q", "main")
        self.s.run_bash("sh t.sh")
        self.s.run_bash("sh t.sh")
        self.assertTrue(self.s.gate("sh t.sh"))
        self.assertEqual(self.s.run_bash("git checkout -q fix")[0], "exit=0")
        self.assertEqual(self.s.run_bash("sh t.sh")[0], "exit=0")

    def test_external_edit_to_tracked_file_reopens(self):
        self.arm()
        with open(os.path.join(self.dir, "x.txt"), "a") as fh:
            fh.write("ide edit\n")
        self.assertFalse(self.s.gate("sh t.sh"))

    def test_13_unborn_head(self):
        d = tempfile.mkdtemp(prefix="hdc-unborn-")
        try:
            git(d, "init", "-q", "-b", "main")
            s = Session(d, self.scratch)
            with open(os.path.join(d, "t.sh"), "w") as fh:
                fh.write("exit 1\n")
            s.run_bash("sh t.sh")
            s.run_bash("sh t.sh")
            self.assertEqual(s.run_bash("sh t.sh")[0], "DENIED")
            with open(os.path.join(d, "new.txt"), "w") as fh:
                fh.write("x\n")
            self.assertFalse(s.gate("sh t.sh"))
            # and it is git-mode, not the nogit fallback
            out = hook("fingerprint", s.base("pre_tool_use"))
            self.assertIn("unborn", out)
            self.assertNotIn("none", out.split()[0])
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------- no-op detector (R2)

class NoopDetector(Base):
    def test_2_noop_sed_on_clean_tracked_file(self):
        cmd = "sed -i 's/zzz/yyy/' x.txt"
        for n in (1, 2):
            status, ctx = self.s.run_bash(cmd)
            self.assertEqual(status, "exit=0")
            self.assertIn(f"failure {n}", ctx)
        self.assertEqual(self.s.run_bash(cmd)[0], "DENIED")

    def test_3_noop_sed_on_dirty_tracked_file(self):
        self.write("x.txt", "foo\ndirty\n")
        _, ctx = self.s.run_bash("sed -i 's/zzz/yyy/' x.txt")
        self.assertIn("matched nothing", ctx)

    def test_4_real_sed_on_gitignored_file_not_flagged(self):
        self.write(".env", "BAD\n")
        status, ctx = self.s.run_bash("sed -i 's/BAD/OK/' .env")
        self.assertEqual((status, ctx), ("exit=0", ""))
        self.assertEqual(self.read(".env"), "OK\n")

    def test_5_real_sed_on_out_of_repo_file_not_flagged(self):
        outside = tempfile.mkdtemp(prefix="hdc-outside-")
        try:
            p = os.path.join(outside, "o.txt")
            with open(p, "w") as fh:
                fh.write("a\n")
            status, ctx = self.s.run_bash(f"sed -i 's/a/b/' {p}")
            self.assertEqual((status, ctx), ("exit=0", ""))
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_6_compound_command_skipped(self):
        status, ctx = self.s.run_bash("sed -i 's/foo/bar/' x.txt && git commit -qam wip")
        self.assertEqual((status, ctx), ("exit=0", ""))
        self.assertIn("bar", git(self.dir, "show", "HEAD:x.txt").stdout)

    def test_r4_1_readonly_perl_with_I_never_flagged(self):
        os.makedirs(os.path.join(self.dir, "lib"))
        self.write("lib/Foo.pm", "package Foo;\nuse strict;\n1;\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "pm")
        for _ in range(3):
            self.assertEqual(self.s.run_bash("perl -c -Ilib lib/Foo.pm"), ("exit=0", ""))

    def test_r4_2_perl_M_switches_not_flagged(self):
        self.assertEqual(self.s.run_bash("perl -Mstrict -ne 'print if /foo/' x.txt"), ("exit=0", ""))
        self.assertEqual(self.s.run_bash("perl -MList::Util=sum -lane 'print $F[0]' x.txt"), ("exit=0", ""))

    def test_r4_3_perl_pi_noop_flagged_and_denied(self):
        cmd = "perl -pi -e 's/zzz/y/' x.txt"
        for n in (1, 2):
            _, ctx = self.s.run_bash(cmd)
            self.assertIn(f"failure {n}", ctx)
        self.assertEqual(self.s.run_bash(cmd)[0], "DENIED")

    def test_r4_4_perl_i_bak_noop_and_real_edit(self):
        _, ctx = self.s.run_bash("perl -i.bak -pe 's/zzz/y/' x.txt")
        self.assertIn("matched nothing", ctx)
        self.assertEqual(self.s.run_bash("perl -pi -e 's/foo/bar/' x.txt"), ("exit=0", ""))
        self.assertEqual(self.read("x.txt"), "bar\n")

    def test_r4_8_quoted_delimiters_are_not_compound(self):
        for cmd in ("sed -i 's|zzz|yyy|' x.txt", "sed -i 's/zzz/y/;s/qqq/z/' x.txt"):
            self.s.reset()
            for n in (1, 2):
                _, ctx = self.s.run_bash(cmd)
                self.assertIn(f"failure {n}", ctx, cmd)
            self.assertEqual(self.s.run_bash(cmd)[0], "DENIED", cmd)

    def _patch_never_flagged(self, cwd, cmd):
        s = Session(cwd, self.scratch)
        status, ctx = s.run_bash(cmd)
        self.assertEqual(status, "exit=0", cmd)
        self.assertEqual(ctx, "", f"patch must never be flagged: {cmd}")

    def test_r5_1_git_apply_cached_not_flagged(self):
        self.write("x.txt", "baz\n")
        with open(os.path.join(self.dir, "c.patch"), "w") as fh:
            fh.write(git(self.dir, "diff").stdout)
        git(self.dir, "checkout", "-q", "x.txt")
        self._patch_never_flagged(self.dir, "git apply --cached c.patch")
        self.assertIn("x.txt", git(self.dir, "diff", "--cached", "--stat").stdout)

    def test_r5_2_rename_mode_binary_patches_not_flagged(self):
        git(self.dir, "mv", "x.txt", "renamed.txt")
        with open(os.path.join(self.dir, "..", "ren.patch"), "w") as fh:
            fh.write(git(self.dir, "diff", "--cached", "-M").stdout)
        git(self.dir, "reset", "-q", "--hard")
        os.chmod(os.path.join(self.dir, "x.txt"), 0o755)
        with open(os.path.join(self.dir, "..", "mode.patch"), "w") as fh:
            fh.write(git(self.dir, "diff").stdout)
        os.chmod(os.path.join(self.dir, "x.txt"), 0o644)
        with open(os.path.join(self.dir, "img.bin"), "wb") as fh:
            fh.write(bytes(range(256)))
        git(self.dir, "add", "img.bin"); git(self.dir, "commit", "-qm", "bin")
        with open(os.path.join(self.dir, "img.bin"), "wb") as fh:
            fh.write(bytes(range(255, -1, -1)))
        with open(os.path.join(self.dir, "..", "bin.patch"), "w") as fh:
            fh.write(git(self.dir, "diff", "--binary").stdout)
        git(self.dir, "checkout", "-q", "img.bin")
        try:
            self._patch_never_flagged(self.dir, "git apply ../ren.patch")
            self.assertTrue(os.path.exists(os.path.join(self.dir, "renamed.txt")))
            git(self.dir, "reset", "-q", "--hard")
            self._patch_never_flagged(self.dir, "git apply ../mode.patch")
            self.assertTrue(os.access(os.path.join(self.dir, "x.txt"), os.X_OK))
            self._patch_never_flagged(self.dir, "git apply ../bin.patch")
        finally:
            for f in ("ren.patch", "mode.patch", "bin.patch"):
                try:
                    os.remove(os.path.join(self.dir, "..", f))
                except OSError:
                    pass

    def test_r5_3_patch_with_explicit_target_not_flagged(self):
        os.makedirs(os.path.join(self.dir, "src"))
        self.write("src/foo.c", "int a = 1;\n")
        with open(os.path.join(self.dir, "..", "n8.patch"), "w") as fh:
            fh.write("--- foo.c.orig\n+++ foo.c\n@@ -1 +1 @@\n-int a = 1;\n+int a = 2;\n")
        try:
            self._patch_never_flagged(self.dir, "patch src/foo.c < ../n8.patch")
            self.assertEqual(self.read("src/foo.c"), "int a = 2;\n")
        finally:
            os.remove(os.path.join(self.dir, "..", "n8.patch"))

    def test_r5_4_git_apply_from_subdirectory_not_flagged(self):
        os.makedirs(os.path.join(self.dir, "sub"))
        self.write("sub/x.txt", "foo\n")
        git(self.dir, "add", "-A"); git(self.dir, "commit", "-qm", "sub")
        self.write("sub/x.txt", "qux\n")
        with open(os.path.join(self.dir, "..", "sub.patch"), "w") as fh:
            fh.write(git(self.dir, "diff").stdout)
        git(self.dir, "checkout", "-q", "sub/x.txt")
        try:
            self._patch_never_flagged(os.path.join(self.dir, "sub"), "git apply ../../sub.patch")
            self.assertEqual(self.read("sub/x.txt"), "qux\n")
        finally:
            os.remove(os.path.join(self.dir, "..", "sub.patch"))

    def test_r5_5_reapplied_patch_goes_through_failure_path(self):
        self.write("x.txt", "bar\n")
        with open(os.path.join(self.dir, "re.patch"), "w") as fh:
            fh.write(git(self.dir, "diff").stdout)
        git(self.dir, "checkout", "-q", "x.txt")
        self.assertEqual(self.s.run_bash("git apply re.patch")[0], "exit=0")
        self.assertEqual(self.s.run_bash("git apply re.patch")[0], "exit=1")
        self.assertEqual(self.s.run_bash("git apply re.patch")[0], "exit=1")
        self.assertEqual(self.s.run_bash("git apply re.patch")[0], "DENIED")

    def test_r5_6_patch_outside_git_and_gitignored_never_flagged(self):
        d = tempfile.mkdtemp(prefix="hdc-nogit-")
        try:
            s = Session(d, self.scratch)
            for cmd in ("patch -p1 < fix.patch", "git apply fix.patch"):
                with open(os.path.join(d, "x.txt"), "w") as fh:
                    fh.write("foo\n")
                with open(os.path.join(d, "fix.patch"), "w") as fh:
                    fh.write("--- a/x.txt\n+++ b/x.txt\n@@ -1 +1 @@\n-foo\n+bar\n")
                self.assertEqual(s.run_bash(cmd), ("exit=0", ""), cmd)
                with open(os.path.join(d, "x.txt")) as fh:
                    self.assertEqual(fh.read(), "bar\n")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_r4_6_real_patch_to_gitignored_file_not_flagged(self):
        self.write(".env", "foo\n")
        with open(os.path.join(self.dir, "..", "env.patch"), "w") as fh:
            fh.write("--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-foo\n+bar\n")
        try:
            self.assertEqual(self.s.run_bash("patch -p1 < ../env.patch"), ("exit=0", ""))
            self.assertEqual(self.read(".env"), "bar\n")
        finally:
            os.remove(os.path.join(self.dir, "..", "env.patch"))


    def test_empty_patch_no_longer_flagged(self):
        with open(os.path.join(self.dir, "empty.patch"), "w") as fh:
            fh.write("")
        self.assertEqual(self.s.run_bash("git apply --allow-empty empty.patch"), ("exit=0", ""))

    def test_sed_without_i_is_not_armed(self):
        self.assertEqual(self.s.run_bash("sed 's/foo/bar/' x.txt")[1], "")


# ----------------------------------------------------- signatures (R5, R6)

PYTEST_OUT = """============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-8.3.2, pluggy-1.5.0
rootdir: /repo
collected 1 item

tests/{file} F                                                        [100%]

=================================== FAILURES ===================================
__________________________________ {test} ___________________________________

    def {test}():
>       assert None == '1Z'
E       AssertionError: assert None == '1Z'

tests/{file}:2: AssertionError
=========================== short test summary info ============================
FAILED tests/{file}::{test} - AssertionError
============================== 1 failed in 0.02s ==============================="""


class Signatures(Base):
    use_git = False

    def test_10_pytest_standard_output_distinguishes_tests(self):
        a = "Exit code 1\n" + PYTEST_OUT.format(file="test_a.py", test="test_ship")
        b = "Exit code 1\n" + PYTEST_OUT.format(file="test_b.py", test="test_bill")
        self.s.fake_fail("pytest tests/test_a.py", a)
        self.assertEqual(self.s.fake_fail("pytest tests/test_b.py", b), "")
        self.assertIn("failed 2 times", self.s.fake_fail("pytest tests/test_a.py", a))

    def test_r5_residual_truncated_pytest_distinguished(self):
        head = "Exit code 1\n=== test session starts ===\nplatform linux -- Python 3.12.3, pytest-8.3.2\ncollected 1 item\n\n"
        self.s.fake_fail("pytest tests/test_a.py", head + "tests/test_a.py F")
        self.assertEqual(self.s.fake_fail("pytest tests/test_b.py", head + "tests/test_b.py F"), "")

    def test_11_python_tracebacks_distinguished(self):
        self.write("a.py", "d = {}\nd['missing']\n")
        self.write("b.py", "import no_such_module\n")
        self.s.run_bash("python3 a.py")
        _, ctx = self.s.run_bash("python3 b.py")
        self.assertEqual(ctx, "")
        _, ctx = self.s.run_bash("python3 a.py")
        self.assertIn("failed 2 times", ctx)
        self.assertIn("keyerror", ctx)

    def test_12_changed_exception_restarts_gate_count(self):
        flag = os.path.join(self.scratch, "mode.txt")
        with open(flag, "w") as fh:
            fh.write("import")
        self.write("c.py", f"m = open('{flag}').read()\nif m == 'import':\n    import no_such_module\nelse:\n    {{}}['missing']\n")
        self.s.run_bash("python3 c.py")
        with open(flag, "w") as fh:
            fh.write("key")
        self.s.run_bash("python3 c.py")
        self.assertEqual(self.s.run_bash("python3 c.py")[0], "exit=1", "count should have restarted")

    def test_11_two_different_pytest_commands_no_reminder(self):
        banner = "============================= test session starts =============================="
        self.s.fake_fail("pytest tests/test_a.py", f"Exit code 1\n{banner}\ncollected 3\nFAILED tests/test_a.py::t")
        out = self.s.fake_fail("pytest tests/test_b.py", f"Exit code 1\n{banner}\ncollected 3\nFAILED tests/test_b.py::u")
        self.assertEqual(out, "")

    def test_same_pytest_failure_twice_reminds(self):
        err = "Exit code 1\n=== test session starts ===\nFAILED tests/test_a.py::t - AssertionError"
        self.s.fake_fail("pytest tests/test_a.py", err)
        self.assertIn("failed 2 times", self.s.fake_fail("pytest tests/test_a.py", err))

    def test_output_less_failures_keyed_by_command_word(self):
        self.s.fake_fail("false", "Exit code 1")
        self.assertEqual(self.s.fake_fail("test -f nope", "Exit code 1"), "")
        self.assertIn("failed 2 times", self.s.fake_fail("false", "Exit code 1"))

    def test_12_hex_request_id_normalised(self):
        self.assertFalse(self.s.gate("./deploy.sh"))
        self.s.fake_fail("./deploy.sh", "Exit code 1\nrequest 7f3a9bc2: upstream refused connection")
        self.assertFalse(self.s.gate("./deploy.sh"))
        self.s.fake_fail("./deploy.sh", "Exit code 1\nrequest a91c03de: upstream refused connection")
        self.assertTrue(self.s.gate("./deploy.sh"))

    def test_r6_glued_unit_durations_normalised(self):
        for t in (5003, 5011):
            self.s.fake_fail("./smoke.sh", f"Exit code 1\nconnecting to api.internal:443\nError: request timed out after {t}ms")
        self.assertTrue(self.s.gate("./smoke.sh"))

    def test_r6_ping_statistics_line_normalised(self):
        ping = lambda t: (f"Exit code 1\nPING db.internal (10.0.0.5) 56(84) bytes of data.\n\n"
                          f"--- db.internal ping statistics ---\n"
                          f"3 packets transmitted, 0 received, 100% packet loss, time {t}ms")
        for t in (2033, 2041):
            self.s.fake_fail("ping -c 3 db.internal", ping(t))
        self.assertTrue(self.s.gate("ping -c 3 db.internal"))

    def test_uuid_normalised(self):
        for u in ("3b241101-e2bb-4255-8caf-4136c566a962", "9f1c2d3e-0a4b-4c5d-8e6f-7a8b9c0d1e2f"):
            self.s.fake_fail("./x", f"Exit code 1\ntrace {u} failed")
        self.assertTrue(self.s.gate("./x"))

    def test_different_error_restarts_count(self):
        self.s.fake_fail("./x", "Exit code 1\nImportError: foo")
        self.s.fake_fail("./x", "Exit code 1\nAssertionError: bar")
        self.assertFalse(self.s.gate("./x"))


# --------------------------------------------- performance and locking

class Performance(Base):
    def test_10_no_git_spawned_when_nothing_armed(self):
        log = os.path.join(self.scratch, "git.log")
        env = dict(os.environ, HDC_GIT_LOG=log)
        p = self.s.pre(None, tool="Read", tool_input={"file_path": os.path.join(self.dir, "x.txt")})
        t = time.time()
        hook("gate", p, env=env)
        hook("success", self.s.base("post_tool_use", tool_name="Read", tool_input=p["tool_input"],
                                    tool_use_id=p["tool_use_id"], tool_response={}), env=env)
        self.assertLess(time.time() - t, 0.5)
        self.assertFalse(os.path.exists(log), "git was spawned for an unarmed Read")

    def test_1_fingerprint_never_writes_the_index(self):
        """Round-2 R1. Porcelain `git diff` refreshes and rewrites
        .git/index (taking index.lock) whenever it meets a tracked file
        that is stat-dirty and not yet refreshed, even under
        GIT_OPTIONAL_LOCKS=0; plumbing diff-files/diff-index never do. The
        reviewer's collision experiment does not reproduce on a fast
        filesystem, so this checks the cause directly. Each round uses a
        fresh tracked file, because git refreshes an entry only once.
        Git skips the opportunistic write on a small index, so the repo
        needs a few thousand tracked files for the test to discriminate.
        Verified to fail against porcelain by swapping diff-files back to
        diff."""
        for i in range(2500):
            self.write(f"t{i}.txt", f"{i}\n")
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-qm", "tracked")
        index = os.path.join(self.dir, ".git", "index")
        payload = self.s.base("pre_tool_use")
        time.sleep(0.05)
        for i in range(5):
            os.utime(os.path.join(self.dir, f"t{i}.txt"))   # stat-dirty, content clean
            time.sleep(0.05)
            before = os.stat(index).st_mtime_ns
            hook("fingerprint", payload)
            self.assertEqual(os.stat(index).st_mtime_ns, before, f"round {i}: index rewritten")

    def test_14_concurrency_inside_git(self):
        for t in range(6):
            s = Session(self.dir, tempfile.mkdtemp(prefix=f"hdc-c{t}-"))
            threads = []
            for i in range(12):
                agent = f"agent_{i % 3}"
                threads.append(threading.Thread(
                    target=s.fake_fail, args=(f"cmd{i}", "Exit code 1\nboom"), kwargs={"agent": agent}))
            threads.append(threading.Thread(
                target=s.edit_tool, args=(os.path.join(self.dir, "x.txt"), "foo", f"foo{t}")))
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            with open(os.path.join(s.scratch, f"hdc-state-{s.sid}.json")) as fh:
                st = json.load(fh)
            self.assertEqual(st["edit_epoch"], 1, f"trial {t}: epoch bump lost")
            self.assertEqual(sum(len(a["calls"]) for a in st["agents"].values()), 12, f"trial {t}")
            shutil.rmtree(s.scratch, ignore_errors=True)


class NoGitFallback(Base):
    use_git = False

    def test_edit_tool_reopens_without_git(self):
        self.write("t.sh", "exit 1\n")
        self.s.run_bash("sh t.sh")
        self.s.run_bash("sh t.sh")
        self.assertTrue(self.s.gate("sh t.sh"))
        self.write("y.txt", "a\n")
        self.s.edit_tool(os.path.join(self.dir, "y.txt"), "a", "b")
        self.assertFalse(self.s.gate("sh t.sh"))

    def test_garbage_input(self):
        r = subprocess.run([PY, SCRIPT, "gate"], input="not json", capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


# ------------------------------------------------- indicators (0.6.0)

REPORT = os.path.join(HERE, "..", "scripts", "hdc_report.py")
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import hdc_hooks  # noqa: E402
import hdc_report  # noqa: E402


def transcript_fixture(version="2.1.270"):
    """Sanitised excerpt of a captured transcript; see fixtures/README.md."""
    with open(os.path.join(FIX, f"transcript_{version}.jsonl")) as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def entries_of(kind, pred=lambda e: True):
    return [e for e in transcript_fixture() if e.get("type") == kind and pred(e)]


def is_deny_entry(e):
    c = e["message"]["content"]
    return isinstance(c, list) and str(c[0].get("content", "")).startswith(hdc_hooks.DENY_PREFIX)


def deny_entry(text, is_error=True):
    e = json.loads(json.dumps(entries_of("user", is_deny_entry)[0]))
    e["message"]["content"][0]["content"] = text
    e["message"]["content"][0]["is_error"] = is_error
    return e


def context_entry(text):
    e = json.loads(json.dumps(entries_of("attachment")[0]))
    e["attachment"]["content"] = [text]
    return e


def prompt_entry(text="next"):
    e = json.loads(json.dumps(entries_of("user", lambda e: isinstance(e["message"]["content"], str))[0]))
    e["message"]["content"] = text
    return e


def tool_use_entry():
    return json.loads(json.dumps(entries_of("assistant")[0]))


class Report(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hdc-projects-")
        self.proj = os.path.join(self.root, hdc_report.encode_project("/repo"))
        os.makedirs(self.proj)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def put(self, entries, name="s1.jsonl", raw_tail=""):
        with open(os.path.join(self.proj, name), "w") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
            fh.write(raw_tail)

    def report(self, *args, env=None):
        r = subprocess.run([PY, "-B", REPORT, "--projects-dir", self.root, "--project", "/repo", *args],
                           capture_output=True, text=True, env=env or dict(os.environ, HDC_EVENTS=""))
        return r

    def data(self, *args):
        r = self.report("--json", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_captured_transcript_counts(self):
        """Turn 1: `false` reminder then deny (one episode), sed no-op twice
        then deny (one episode, depth 3, pre-0.4 wording). Turn 2: `false`
        re-run after the user's message (a deny cleared by a user turn), and
        its reminder opens a new episode."""
        self.put(transcript_fixture())
        d = self.data()
        self.assertEqual((d["sessions"], d["tool_calls"], d["denies"], d["reminders"], d["noops"]),
                         (1, 7, 2, 2, 2))
        self.assertEqual((d["episodes"], d["max_depth"], d["past_gate"], d["cleared_by_user"]),
                         (3, 3, 0, 1))

    def test_captured_2_1_289_wrapped_deny(self):
        """Found in the 0.6.0 live run: 2.1.289 stores a deny as
        "PreToolUse:Bash hook error: <reason>". `sh -c 'exit 1'` fails twice
        (reminder), then is denied: one episode of depth 2."""
        entries = transcript_fixture("2.1.289")
        self.assertTrue(any("hook error: " + hdc_hooks.DENY_PREFIX in json.dumps(e) for e in entries))
        self.put(entries)
        d = self.data()
        self.assertEqual((d["tool_calls"], d["denies"], d["reminders"], d["episodes"], d["max_depth"]),
                         (3, 1, 1, 1, 2))

    def test_printed_deny_text_is_not_a_deny(self):
        """Found against real transcripts: a Bash call that printed a
        captured deny message was counted as a deny."""
        self.put([prompt_entry(), tool_use_entry(), deny_entry(hdc_hooks.DENY_PREFIX + "Bash(x) has failed 2 times "
                                             'with the same error ("e")', is_error=False)])
        self.assertEqual(self.data()["denies"], 0)

    def test_task_notification_is_not_a_turn(self):
        sig = 'with the same signature: "exit 1:". The Hierarchy'
        self.put([prompt_entry(), tool_use_entry(), context_entry(f"The Bash tool has now failed 2 times in this session {sig}"),
                  prompt_entry("<task-notification>\n<task-id>x</task-id>"),
                  deny_entry(hdc_hooks.DENY_PREFIX + 'Bash(false) has failed 2 times with the same error ("exit 1:")')])
        d = self.data()
        self.assertEqual((d["episodes"], d["max_depth"]), (1, 2))

    def test_repeated_denies_continue_past_the_gate(self):
        deny = deny_entry(hdc_hooks.DENY_PREFIX + 'Bash(false) has failed 2 times with the same error ("exit 1:")')
        self.put([prompt_entry(), tool_use_entry(), deny, deny, prompt_entry(), deny])
        d = self.data()
        self.assertEqual((d["episodes"], d["max_depth"], d["past_gate"]), (2, 2, 1))

    def test_only_a_retry_after_a_user_turn_clears_a_deny(self):
        call = entries_of("assistant")[2]                 # the `false` the fixture's first deny answers
        deny = entries_of("user", is_deny_entry)[0]
        self.assertEqual(call["message"]["content"][0]["id"], deny["message"]["content"][0]["tool_use_id"])
        self.put([prompt_entry(), call, deny, call, deny])
        self.assertEqual(self.data()["cleared_by_user"], 0)
        self.put([prompt_entry(), call, deny, call, deny, prompt_entry(), call])
        self.assertEqual(self.data()["cleared_by_user"], 1)

    def test_malformed_line_counted_not_fatal(self):
        self.put(transcript_fixture(), raw_tail='{"type":"user","mess')
        r = self.report()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Malformed transcript lines skipped: 1", r.stdout)
        self.assertIn("Observed: 1 sessions", r.stdout.splitlines()[1])

    def test_rate_only_from_twenty_episodes(self):
        rem = 'The Bash tool has now failed 2 times in this session with the same signature: "e". The Hierarchy'
        self.put([x for _ in range(19) for x in (prompt_entry(), tool_use_entry(), context_entry(rem))])
        self.assertIsNone(self.data()["rate_per_1000"])
        self.assertIn("N<20, no rate", self.report().stdout)
        self.put([x for _ in range(20) for x in (prompt_entry(), tool_use_entry(), context_entry(rem))])
        rate = self.data()["rate_per_1000"]
        self.assertAlmostEqual(rate["value"], 1000.0)
        self.assertLess(rate["ci95"][0], 1000.0)
        self.assertGreater(rate["ci95"][1], 1000.0)

    def test_poisson_interval(self):
        lo, hi = hdc_report.poisson_ci(2)
        self.assertEqual((round(lo, 3), round(hi, 3)), (0.242, 7.225))
        lo, hi = hdc_report.poisson_ci(0)
        self.assertEqual((lo, round(hi, 3)), (0.0, 3.689))

    def test_since_filters_by_entry_timestamp(self):
        self.put(transcript_fixture())
        self.assertEqual(self.data("--since", "2026-09-15")["sessions"], 0)
        self.assertEqual(self.data("--since", "2026-09-14")["sessions"], 1)

    def test_subagent_transcripts_counted_separately(self):
        self.put(transcript_fixture())
        os.makedirs(os.path.join(self.proj, "s1", "subagents"))
        self.put(transcript_fixture(), name=os.path.join("s1", "subagents", "agent-a.jsonl"))
        d = self.data()
        self.assertEqual((d["sessions"], d["subagents"], d["denies"]), (1, 1, 4))

    def test_unknown_project_fails_loudly(self):
        r = subprocess.run([PY, "-B", REPORT, "--projects-dir", self.root, "--project", "/nowhere"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no transcripts for /nowhere", r.stderr)

    def test_tier4_section(self):
        self.put(transcript_fixture())
        self.assertIn("HDC_EVENTS not set", self.report().stdout)
        ev = os.path.join(self.root, "events.jsonl")
        with open(ev, "w") as fh:
            fh.write(json.dumps({"ts": "2026-09-20T00:00:00Z", "kind": "hook_exception", "version": "0.6.0"}) + "\n")
        out = self.report(env=dict(os.environ, HDC_EVENTS=ev)).stdout
        self.assertIn("1 records: hook_exception 1", out)
        self.assertIn("Zero is not evidence of health", out)


class ReportDrift(Base):
    """The report parses the hooks' own messages back out of transcripts.
    Feed it what the hooks actually emit today."""

    def test_current_messages_are_parsed(self):
        self.write("t.sh", "exit 1\n")
        self.s.run_bash("sh t.sh")
        _, reminder = self.s.run_bash("sh t.sh")
        deny = json.loads(hook("gate", self.s.pre("sh t.sh")))["hookSpecificOutput"]["permissionDecisionReason"]
        _, noop = self.s.run_bash("sed -i 's/zzz/yyy/' x.txt")
        self.s.run_bash("sed -i 's/zzz/yyy/' x.txt")
        noop_deny = json.loads(hook("gate", self.s.pre("sed -i 's/zzz/yyy/' x.txt")))[
            "hookSpecificOutput"]["permissionDecisionReason"]
        self.assertTrue(hdc_hooks.REMINDER_RE.match(reminder), reminder)
        self.assertTrue(hdc_hooks.DENY_RE.match(deny), deny)
        self.assertTrue(hdc_hooks.NOOP_RE.match(noop), noop)

        root = tempfile.mkdtemp(prefix="hdc-projects-")
        try:
            proj = os.path.join(root, "p")
            os.makedirs(proj)
            with open(os.path.join(proj, "s.jsonl"), "w") as fh:
                for e in (prompt_entry(), tool_use_entry(), context_entry(reminder), deny_entry(deny),
                          context_entry(noop), context_entry(noop), deny_entry(noop_deny)):
                    fh.write(json.dumps(e) + "\n")
            d = hdc_report.build([proj])
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual((d["denies"], d["reminders"], d["noops"]), (2, 1, 2))
        self.assertEqual((d["episodes"], d["max_depth"]), (2, 3))


class Tier4(Base):
    def setUp(self):
        super().setUp()
        self.events = os.path.join(self.scratch, "events.jsonl")
        os.environ["HDC_EVENTS"] = self.events

    def tearDown(self):
        os.environ.pop("HDC_EVENTS", None)
        super().tearDown()

    def records(self):
        if not os.path.exists(self.events):
            return []
        with open(self.events) as fh:
            return [json.loads(ln) for ln in fh]

    def broken_success(self, env=None):
        """`success` with scratchpad_dir pointing at a file: State() raises."""
        blocker = os.path.join(self.scratch, "not-a-dir")
        open(blocker, "w").close()
        p = self.s.base("post_tool_use", tool_name="Bash", tool_input={"command": "secret-cmd"},
                        tool_use_id="toolu_x", tool_response={}, scratchpad_dir=blocker)
        # Timeout so a blocking write fails this test instead of hanging the suite.
        return subprocess.run([PY, SCRIPT, "success"], input=json.dumps(p), capture_output=True, text=True,
                              check=False, env=env or os.environ, timeout=5).stdout

    def test_off_by_default(self):
        env = dict(os.environ)
        env.pop("HDC_EVENTS")
        self.assertEqual(self.broken_success(env=env), "")
        self.assertEqual(self.records(), [])

    def test_swallowed_exception_is_recorded(self):
        self.assertEqual(self.broken_success(), "")       # session still sees nothing
        (r,) = self.records()
        self.assertEqual((r["kind"], r["mode"], r["exc_type"], r["session_id"]),
                         ("hook_exception", "success", "NotADirectoryError", self.s.sid))
        self.assertEqual((r["version"], r["schema"], r["threshold"]),
                         (hdc_hooks.VERSION, hdc_hooks.SCHEMA, hdc_hooks.THRESHOLD))
        self.assertEqual(r["func"], "__enter__")
        self.assertNotIn("secret-cmd", json.dumps(r))
        self.assertEqual(os.stat(self.events).st_mode & 0o777, 0o600)

    def test_corrupt_state_is_recorded_and_healed(self):
        with open(os.path.join(self.scratch, f"hdc-state-{self.s.sid}.json"), "w") as fh:
            fh.write("{truncated")
        self.s.reset()
        self.assertEqual([(r["kind"], r["session_id"]) for r in self.records()],
                         [("state_corrupt", self.s.sid)])
        self.s.reset()
        self.assertEqual(len(self.records()), 1)          # rewritten whole

    def test_fifo_target_never_blocks_and_deny_survives(self):
        os.mkfifo(self.events)
        t = time.time()
        self.broken_success()
        self.assertLess(time.time() - t, 2)
        self.arm()
        self.assertEqual(self.s.run_bash("sh t.sh"), ("DENIED", ""))

    def test_relative_path_ignored(self):
        env = dict(os.environ, HDC_EVENTS="events.jsonl")
        self.broken_success(env=env)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "events.jsonl")))
        self.assertFalse(os.path.exists("events.jsonl"))

    def test_parallel_appends_stay_whole(self):
        threads = [threading.Thread(target=self.broken_success) for _ in range(13)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(self.records()), 13)         # each line parsed

    def test_normal_operation_writes_nothing(self):
        self.arm()
        self.s.run_bash("sh t.sh")
        self.s.reset()
        self.assertEqual(self.records(), [])

    def test_version_matches_manifests(self):
        root = os.path.join(HERE, "..", ".claude-plugin")
        with open(os.path.join(root, "plugin.json")) as fh:
            self.assertEqual(json.load(fh)["version"], hdc_hooks.VERSION)
        with open(os.path.join(root, "marketplace.json")) as fh:
            self.assertEqual(json.load(fh)["plugins"][0]["version"], hdc_hooks.VERSION)


if __name__ == "__main__":
    unittest.main(verbosity=1)
