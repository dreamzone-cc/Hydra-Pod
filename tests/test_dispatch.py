import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydra_pod import dispatch, ticket as tk
from hydra_pod.status import ProviderStatus, State

TICKET = """---
ticket: T9-demo
state: open
worker: opencode-go/deepseek-v4.1-flash
base:
head:
test_command: python3 -B -m unittest discover -s tests -v
allowed_files:
  - src/app.py
acceptance:
  - test -f src/app.py
  - echo hello world ==> hello
earlier_specs:
  - _tickets/done/T1-old.md
---
# T9: demo feature

> claimed-by: (the manager fills this in at dispatch)

Body text.
"""


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class TicketHeaderTests(unittest.TestCase):
    def test_parse_and_roundtrip(self):
        header, body = tk.parse_header(TICKET)
        self.assertEqual(header["ticket"], "T9-demo")
        self.assertEqual(header["allowed_files"], ["src/app.py"])
        self.assertEqual(header["base"], "")
        self.assertTrue(body.startswith("# T9: demo feature"))
        again = tk.render_header(header) + body
        self.assertEqual(tk.parse_header(again), (header, body))

    def test_acceptance_expectation(self):
        header, _ = tk.parse_header(TICKET)
        t = tk.Ticket(Path("x.md"), header, "")
        self.assertEqual([(a.command, a.expect) for a in t.acceptance],
                         [("test -f src/app.py", None), ("echo hello world", "hello")])

    def test_validate_and_errors(self):
        t = tk.Ticket(Path("x.md"), {"state": "weird"}, "")
        problems = " ".join(t.validate())
        for word in ("state", "allowed_files", "acceptance", "test_command"):
            self.assertIn(word, problems)
        with self.assertRaises(ValueError):
            tk.parse_header("---\nticket: x\n")
        self.assertEqual(tk.parse_header("# no header\n"), ({}, "# no header\n"))


class DispatchFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        sh(self.p, "git", "init", "-q")
        sh(self.p, "git", "config", "user.email", "t@example.com")
        sh(self.p, "git", "config", "user.name", "t")
        for d in ("open", "doing", "done"):
            (self.p / "_tickets" / d).mkdir(parents=True)
        (self.p / "_receipts").mkdir()
        (self.p / "src").mkdir()
        (self.p / "src" / "keep.py").write_text("x = 1\n")
        sh(self.p, "git", "add", "-A")
        sh(self.p, "git", "commit", "-qm", "init")
        (self.p / "_tickets" / "open" / "T9-demo.md").write_text(TICKET)  # untracked on purpose
        self.env = mock.patch.dict(os.environ, {"HYDRA_POD_COMMIT_TRAILER": "Trailer: test"})
        self.env.start()
        # No test may reach real accounts or the network: preflight is stubbed here
        # and exercised with its own mocks in PreflightAndCostTests.
        self.pf = mock.patch.object(dispatch, "preflight_checks", return_value=[("stub", True, "")])
        self.pf.start()

    def tearDown(self):
        self.pf.stop()
        self.env.stop()
        self.tmp.cleanup()

    def log(self):
        return subprocess.run(["git", "log", "--format=%s%n%b"], cwd=self.p,
                              capture_output=True, text=True).stdout

    def test_claim_accept_close(self):
        dispatch.claim(self.p, "T9-demo")
        t = tk.find(self.p, "T9-demo")
        self.assertEqual((t.state, t.path.parent.name), ("doing", "doing"))
        self.assertTrue(t.header["base"])
        self.assertIn("claimed-by: opencode / opencode-go/deepseek-v4.1-flash @", t.body)
        self.assertIn("T9-demo: open ticket", self.log())
        self.assertIn("Trailer: test", self.log())

        # worker output: allowed file + its receipt
        (self.p / "src" / "app.py").write_text("print('hi')\n")
        (self.p / "_receipts" / "T9-demo.receipt.md").write_text("receipt\n")
        dispatch.accept(self.p, "T9-demo")
        t = tk.find(self.p, "T9-demo")
        self.assertEqual(t.state, "review")
        self.assertTrue(t.header["head"])
        self.assertIn("T9-demo: T9: demo feature", self.log())
        evidence = (self.p / "_receipts" / "T9-demo.acceptance.md").read_text()
        self.assertEqual(evidence.count("PASS"), 2)
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=self.p,
                                        capture_output=True, text=True).stdout.strip(), "")

        dispatch.close(self.p, "T9-demo")
        t = tk.find(self.p, "T9-demo")
        self.assertEqual((t.state, t.path.parent.name), ("done", "done"))

    def test_accept_rejects_out_of_scope_changes(self):
        dispatch.claim(self.p, "T9-demo")
        (self.p / "src" / "app.py").write_text("ok\n")
        (self.p / "src" / "keep.py").write_text("x = 2\n")        # not allowed
        with self.assertRaises(dispatch.Abort) as ctx:
            dispatch.accept(self.p, "T9-demo")
        self.assertIn("src/keep.py", str(ctx.exception))

    def test_accept_failing_command_does_not_commit(self):
        dispatch.claim(self.p, "T9-demo")                          # src/app.py missing -> test -f fails
        before = self.log()
        with self.assertRaises(dispatch.Abort):
            dispatch.accept(self.p, "T9-demo")
        self.assertEqual(self.log(), before)
        self.assertIn("FAIL", (self.p / "_receipts" / "T9-demo.acceptance.md").read_text())

    def test_claim_stops_on_failed_preflight(self):
        self.pf.stop()
        with mock.patch.object(dispatch, "preflight_checks",
                               return_value=[("builder account (opencode-go)", False, "Not Connected")]):
            with self.assertRaises(dispatch.Abort):
                dispatch.claim(self.p, "T9-demo")
        self.pf.start()
        self.assertEqual(tk.find(self.p, "T9-demo").state, "open")   # nothing moved

    def test_state_guards(self):
        with self.assertRaises(dispatch.Abort):
            dispatch.accept(self.p, "T9-demo")                     # still open
        dispatch.claim(self.p, "T9-demo")
        with self.assertRaises(dispatch.Abort):
            dispatch.claim(self.p, "T9-demo")                      # already doing

    def test_manager_files_are_not_out_of_scope(self):
        dispatch.claim(self.p, "T9-demo")
        (self.p / "_tickets" / "STATE.md").write_text("x")
        (self.p / "_receipts" / "T3-other.diff").write_text("x")
        t = tk.find(self.p, "T9-demo")
        self.assertEqual(dispatch.out_of_scope(t, dispatch.changed_files(self.p, t.header["base"])), [])

    def test_review_prompt_is_fully_filled(self):
        dispatch.claim(self.p, "T9-demo")
        t = tk.find(self.p, "T9-demo")
        t.header["head"] = "abc1234"
        text = dispatch.review_prompt(self.p, t, "opencode")
        for placeholder in ("<ticket>", "<base>", "<head>", "<now>", "<test command>", "<earlier specs>"):
            self.assertNotIn(placeholder, text)
        self.assertIn(f"{t.header['base']}..abc1234", text)
        self.assertIn("python3 -B -m unittest discover -s tests -v", text)
        self.assertIn("_tickets/done/T1-old.md", text)
        self.assertIn("PROBE:", text)

    def _review_with(self, rc, report_text):
        dispatch.claim(self.p, "T9-demo")
        (self.p / "src" / "app.py").write_text("ok\n")
        (self.p / "_receipts" / "T9-demo.receipt.md").write_text("r\n")
        dispatch.accept(self.p, "T9-demo")
        done = subprocess.CompletedProcess([], rc, report_text)
        with mock.patch.object(dispatch, "gate_opencode_label"), \
             mock.patch.object(dispatch.quota, "zai_quota", return_value=None), \
             mock.patch.object(dispatch.subprocess, "run", return_value=done), \
             mock.patch("sys.stdout"):
            dispatch.review(self.p, "T9-demo", "opencode")

    def test_review_keeps_complete_report_despite_late_transport_error(self):
        self._review_with(1, "Reviewer: x at t\nVerdict: fine. No findings.\n")
        self.assertIn("No findings", (self.p / "_receipts" / "T9-demo.review.md").read_text())

    def test_review_without_complete_report_fails(self):
        with self.assertRaises(dispatch.Abort):
            self._review_with(0, "partial thinking, no header")

    def test_build_stops_when_builder_not_connected(self):
        dispatch.claim(self.p, "T9-demo")
        down = mock.Mock(status=mock.Mock(return_value=ProviderStatus("opencode-go", State.NOT_CONNECTED)))
        with mock.patch.object(dispatch.registry, "get", return_value=down), \
             mock.patch.object(dispatch.subprocess, "run", side_effect=AssertionError("must not run")):
            with self.assertRaises(dispatch.Abort) as ctx:
                dispatch.build(self.p, "T9-demo")
        self.assertIn("hydra-pod-connect connect opencode-go", str(ctx.exception))

    def test_headerless_ticket_state_comes_from_folder(self):
        (self.p / "_tickets" / "done" / "T1-old.md").write_text("# T1: old ticket without header\n")
        self.assertEqual(tk.find(self.p, "T1-old").state, "done")

    def test_status_writes_state_file(self):
        with mock.patch("sys.stdout"):
            dispatch.status(self.p)
        text = (self.p / "_tickets" / "STATE.md").read_text()
        self.assertIn("| T9-demo | open |", text)
        self.assertIn("hydra-pod-dispatch claim T9-demo", text)


class PreflightAndCostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name)
        sh(self.p, "git", "init", "-q")
        (self.p / "_tickets" / "open").mkdir(parents=True)
        (self.p / "_receipts").mkdir()
        (self.p / "_tickets" / "open" / "T9-demo.md").write_text(
            TICKET.replace("earlier_specs:", "reviewers:\n  - opencode\n  - zcode\nearlier_specs:"))
        self.t = tk.find(self.p, "T9-demo")

    def tearDown(self):
        self.tmp.cleanup()

    def checks(self, *, provider=None, label=None, q=None):
        with mock.patch.object(dispatch, "provider_problem", side_effect=lambda pid: (provider or {}).get(pid)), \
             mock.patch.object(dispatch, "opencode_label_problem", return_value=label), \
             mock.patch.object(dispatch.quota, "zai_quota", return_value=q):
            return {name: (ok, detail) for name, ok, detail in dispatch.preflight_checks(self.p, self.t)}

    def test_all_accounts_and_credits_ok(self):
        q = {"level": "lite", "windows": [{"window": "5h", "used": 10, "total": 2000, "remaining": 1990, "resets_at": None}]}
        c = self.checks(q=q)
        self.assertTrue(all(ok for ok, _ in c.values()), c)
        self.assertIn("reviewer account (zcode-lite)", c)
        self.assertIn("reviewer account (opencode / Z.AI Coding Plan)", c)

    def test_disconnected_reviewer_and_low_credits_fail_with_hint(self):
        q = {"level": "lite", "windows": [{"window": "5h", "used": 1950, "total": 2000, "remaining": 50, "resets_at": None}]}
        c = self.checks(provider={"zcode-lite": "zcode-lite is Not Connected; " +
                                  dispatch.CONNECT_HINT.format(p="zcode-lite")}, q=q)
        self.assertFalse(c["reviewer account (zcode-lite)"][0])
        self.assertIn("separate terminal", c["reviewer account (zcode-lite)"][1])
        self.assertFalse(c[f"Z.ai credits >= {dispatch.MIN_ZAI_CREDITS}"][0])

    def test_unknown_quota_is_a_warning_not_a_failure(self):
        c = self.checks(q=None)
        self.assertIsNone(c["Z.ai credits"][0])

    def test_jsonl_metrics_reads_tokens_and_cost(self):
        f = self.p / "run.jsonl"
        f.write_text("\n".join([
            '{"type":"step_start","timestamp":1000}',
            '{"type":"tool_use","timestamp":2000,"part":{"state":{"status":"completed"}}}',
            '{"type":"tool_use","timestamp":3000,"part":{"state":{"status":"error"}}}',
            '{"type":"step_finish","timestamp":4000,"part":{"cost":0.5,"tokens":{"input":100,"output":7,"reasoning":3,"cache":{"read":20}}}}',
            '{"type":"step_finish","timestamp":6000,"part":{"cost":0.25,"tokens":{"input":50,"output":3,"reasoning":0,"cache":{"read":0}}}}']))
        m = dispatch.jsonl_metrics(f)
        self.assertEqual((m["seconds"], m["tool_calls"], m["denied"]), (5, 2, 1))
        self.assertEqual(m["tokens"], {"input": 150, "output": 10, "reasoning": 3, "cache_read": 20})
        self.assertEqual(m["list_cost_usd"], 0.75)

    def test_cost_log_and_totals(self):
        dispatch.record_cost(self.p, "T9-demo", {"phase": "build", "seconds": 30,
                             "tokens": {"input": 100, "output": 10, "reasoning": 5}, "list_cost_usd": 0.01})
        dispatch.record_cost(self.p, "T9-demo", {"phase": "review", "seconds": 60, "zai_credits": 12,
                             "tokens": {"input": 50, "output": 5, "reasoning": 0}})
        entries = dispatch.load_costs(self.p, "T9-demo")
        self.assertEqual([e["phase"] for e in entries], ["build", "review"])
        self.assertTrue(all("at" in e for e in entries))
        tot = dispatch.cost_totals(entries)
        self.assertEqual((tot["runs"], tot["seconds"], tot["tokens"], tot["zai_credits"]), (2, 90, 170, 12))

    def test_quota_difference(self):
        from hydra_pod import quota
        w = lambda used: {"level": "lite", "windows": [{"window": "5h", "used": used, "total": 2000,
                                                          "remaining": 2000 - used, "resets_at": None}]}
        self.assertEqual(quota.used_between(w(100), w(115)), 15)
        self.assertIsNone(quota.used_between(w(900), w(5)))        # window reset in between
        self.assertIsNone(quota.used_between(None, w(5)))


class EnvLegacyTests(unittest.TestCase):
    """Each new variable wins; when it is unset its legacy name is used."""

    def test_commit_trailer_new_wins(self):
        with mock.patch.dict(os.environ, {"HYDRA_POD_COMMIT_TRAILER": "New: x",
                                          "OM_COMMIT_TRAILER": "Old: y"}, clear=True):  # legacy name
            self.assertEqual(
                dispatch.env_or_legacy("HYDRA_POD_COMMIT_TRAILER", "OM_COMMIT_TRAILER"), "New: x")

    def test_commit_trailer_legacy_when_new_unset(self):
        with mock.patch.dict(os.environ, {"OM_COMMIT_TRAILER": "Old: y"}, clear=True):  # legacy name only
            self.assertEqual(
                dispatch.env_or_legacy("HYDRA_POD_COMMIT_TRAILER", "OM_COMMIT_TRAILER"), "Old: y")

    def test_empty_new_value_beats_legacy(self):
        with mock.patch.dict(os.environ, {"HYDRA_POD_COMMIT_TRAILER": "",  # empty but set
                                          "OM_COMMIT_TRAILER": "Old: y"}, clear=True):  # legacy name
            self.assertEqual(
                dispatch.env_or_legacy("HYDRA_POD_COMMIT_TRAILER", "OM_COMMIT_TRAILER"), "")

    def test_min_credits_new_wins(self):
        with mock.patch.dict(os.environ, {"HYDRA_POD_MIN_ZAI_CREDITS": "7",
                                          "OM_MIN_ZAI_CREDITS": "9"}, clear=True):  # legacy name
            self.assertEqual(
                dispatch.env_or_legacy("HYDRA_POD_MIN_ZAI_CREDITS", "OM_MIN_ZAI_CREDITS", "100"), "7")

    def test_min_credits_legacy_when_new_unset(self):
        with mock.patch.dict(os.environ, {"OM_MIN_ZAI_CREDITS": "9"}, clear=True):  # legacy name only
            self.assertEqual(
                dispatch.env_or_legacy("HYDRA_POD_MIN_ZAI_CREDITS", "OM_MIN_ZAI_CREDITS", "100"), "9")

    def test_default_when_neither_is_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                dispatch.env_or_legacy("HYDRA_POD_MIN_ZAI_CREDITS", "OM_MIN_ZAI_CREDITS", "100"), "100")
            self.assertEqual(
                dispatch.env_or_legacy("HYDRA_POD_COMMIT_TRAILER", "OM_COMMIT_TRAILER"), "")


class InstallShEnvTests(unittest.TestCase):
    """HYDRA_POD_BIN_DIR wins in install.sh; OM_BIN_DIR (legacy) is used when it is unset."""

    def _run(self, **env):
        repo = Path(__file__).resolve().parents[1]
        e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        e.update(env)
        return subprocess.run(["bash", str(repo / "scripts/install.sh")],
                              capture_output=True, text=True, env=e)

    def test_new_bin_dir_wins_over_legacy(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b, \
             tempfile.TemporaryDirectory() as c:
            r = self._run(HOME=c, CLAUDE_HOME=c, HYDRA_POD_BIN_DIR=a, OM_BIN_DIR=b)  # legacy name
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(a) / "hydra-pod-connect").is_symlink())
            self.assertTrue((Path(a) / "hydra-pod-dispatch").is_symlink())
            self.assertFalse((Path(b) / "hydra-pod-connect").exists())

    def test_legacy_bin_dir_when_new_unset(self):
        with tempfile.TemporaryDirectory() as b, tempfile.TemporaryDirectory() as c:
            r = self._run(HOME=c, CLAUDE_HOME=c, OM_BIN_DIR=b)  # legacy name only
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((Path(b) / "hydra-pod-connect").is_symlink())


if __name__ == "__main__":
    unittest.main()
