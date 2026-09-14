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


if __name__ == "__main__":
    unittest.main(verbosity=1)
