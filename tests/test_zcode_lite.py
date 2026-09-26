import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydra_pod import paths, state_store
from hydra_pod.providers import zcode_lite
from hydra_pod.runtime import zcode as zrt
from hydra_pod.runtime.proc import Result
from hydra_pod.status import ProviderStatus, State

SPEC = {"kind": "zcode-cli", "login_target": "zai",
        "expected_model": "account:zai-individual-coding-plan/GLM-5.3"}
RT = zrt.Runtime("3.14.3", "0.16.9", "/x.AppImage", "/rt", "/rt/glm/zcode.cjs", "0" * 64)


class ZCodeLiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(paths, "ZCODE_HOME", d / "zh"),
            mock.patch.object(paths, "CACHE_DIR", d / "cache"),
            mock.patch.object(paths, "STATUS_CACHE", d / "cache" / "status.json"),
            mock.patch.object(zrt, "installed", return_value=RT),
        ]
        for p in self.patches:
            p.start()
        self.p = zcode_lite.ZCodeLite("zcode-lite", SPEC)
        self.session = d / "zh" / ".zcode" / "v2" / "credentials.json"

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def login(self):
        self.session.parent.mkdir(parents=True, exist_ok=True)
        self.session.write_text("{}")

    # status: no quota, no reading of session content
    def test_status_without_session_is_not_connected(self):
        st = self.p.status()
        self.assertEqual(st.state, State.NOT_CONNECTED)
        self.assertTrue(st.verified)

    def test_status_reuses_live_result_only_if_session_unchanged(self):
        self.login()
        os.utime(self.session, (time.time() - 100, time.time() - 100))
        state_store.save(ProviderStatus("zcode-lite", State.EXPIRED, verified=True))
        self.assertEqual(self.p.status().state, State.EXPIRED)
        os.utime(self.session, None)  # new login after the check
        st = self.p.status()
        self.assertEqual(st.state, State.CONNECTED)
        self.assertFalse(st.verified)

    def test_status_never_opens_session_file(self):
        self.login()
        real_open = open
        def guarded(path, *a, **k):
            if Path(path) == self.session:
                raise AssertionError("session file must not be opened")
            return real_open(path, *a, **k)
        with mock.patch("builtins.open", guarded):
            self.p.status()

    # test: one call, all tools removed, isolated env
    def test_live_ok(self):
        with mock.patch.object(zcode_lite, "run", return_value=Result(0, json.dumps({"response": "OK"}), "")) as r:
            st = self.p.test()
        self.assertEqual((st.state, st.verified), (State.CONNECTED, True))
        argv, env = r.call_args.args[0], r.call_args.kwargs["env"]
        self.assertIn("--disallowed-tools", argv)
        for tool in ("Write", "Edit", "Bash", "js", "EvalWorkflowSnippet", "Agent"):
            self.assertIn(tool, argv[argv.index("--disallowed-tools") + 1].split())
        self.assertEqual(env["ZCODE_DATA_BASE_DIR"], str(paths.ZCODE_HOME))
        self.assertEqual(env["HOME"], os.environ["HOME"])

    def test_live_failures_are_classified(self):
        cases = {"Error: Model creation failed (traceId: t)": State.NOT_CONNECTED,
                 "HTTP 401 Unauthorized": State.EXPIRED,
                 "1310 Weekly/Monthly Limit Exhausted": State.CONNECTED}
        for err, state in cases.items():
            with self.subTest(err=err), mock.patch.object(zcode_lite, "run", return_value=Result(1, "", err)):
                self.assertEqual(self.p.test().state, state)

    # connect: official login, JSON captured (account details not printed), then test
    def test_connect_success_then_verifies(self):
        out = json.dumps({"status": "ready", "provider": "zai", "user": {"email": "x@y"},
                          "model": SPEC["expected_model"]})
        with mock.patch.object(zcode_lite.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, out)) as sp, \
             mock.patch.object(zcode_lite, "run", return_value=Result(0, '{"response":"OK"}', "")):
            st = self.p.connect(open_browser=False)
        argv = sp.call_args.args[0]
        self.assertEqual(argv[-4:], ["login", "zai", "--json", "--no-browser"])
        self.assertEqual(sp.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertNotIn("stderr", sp.call_args.kwargs)  # official URL/messages reach the user
        self.assertEqual((st.state, st.model), (State.CONNECTED, SPEC["expected_model"]))
        self.assertNotIn("x@y", json.dumps(st.to_dict()))

    @mock.patch.object(zcode_lite.time, "sleep")
    def test_connect_timeout_and_failure(self, _sleep):
        with mock.patch.object(zcode_lite.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("zcode", 330)):
            self.assertEqual(self.p.connect().state, State.AUTH_FAILED)
        with mock.patch.object(zcode_lite.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1, "")):
            self.assertEqual(self.p.connect().state, State.AUTH_FAILED)

    def test_connect_retries_fast_flow_start_failures(self):
        ok = subprocess.CompletedProcess([], 0, json.dumps({"status": "ready", "model": SPEC["expected_model"]}))
        with mock.patch.object(zcode_lite.subprocess, "run",
                               side_effect=[subprocess.CompletedProcess([], 1, ""), ok]) as sp, \
             mock.patch.object(zcode_lite.time, "sleep"), \
             mock.patch.object(zcode_lite, "run", return_value=Result(0, '{"response":"OK"}', "")):
            st = self.p.connect()
        self.assertEqual(sp.call_count, 2)
        self.assertEqual(st.state, State.CONNECTED)

    @mock.patch.object(zcode_lite.time, "sleep")
    def test_connect_marks_authenticating_while_waiting(self, _sleep):
        seen = {}
        def fake(*a, **k):
            seen["state"] = state_store.load()["zcode-lite"].state
            return subprocess.CompletedProcess([], 1, "")
        with mock.patch.object(zcode_lite.subprocess, "run", side_effect=fake):
            self.p.connect()
        self.assertEqual(seen["state"], State.AUTHENTICATING)

    # reviewer: only Read/Glob/Grep, MCP off, verified before use
    def test_reviewer_command_allows_only_read_tools(self):
        argv = self.p.worker_command("reviewer", "review this")
        denied = argv[argv.index("--disallowed-tools") + 1].split()
        for t in ("Read", "Glob", "Grep"):
            self.assertNotIn(t, denied)
        for t in ("Write", "Edit", "Bash", "js", "mcp__node_repl__js", "Agent",
                  "EvalWorkflowSnippet", "CreateWorkflow", "EnterPlanMode", "WebFetch", "Skill"):
            self.assertIn(t, denied)
        self.assertEqual(argv[argv.index("--mode") + 1], "yolo")
        cwd = Path(argv[argv.index("--cwd") + 1])
        self.assertEqual(json.loads((cwd / ".zcode" / "config.json").read_text()),
                         {"features": {"mcp": False}})

    def test_reviewer_role_only(self):
        with self.assertRaises(NotImplementedError):
            self.p.worker_command("builder", "x")

    def test_verify_reviewer_accepts_exact_set_and_caches(self):
        reply = Result(0, json.dumps({"response": "Glob\nGrep\nRead"}), "")
        with mock.patch.object(zcode_lite, "run", return_value=reply) as r:
            self.assertTrue(self.p.verify_reviewer()[0])
            self.assertTrue(self.p.verify_reviewer()[0])
        self.assertEqual(r.call_count, 1)  # second call uses the per-runtime marker

    def test_verify_reviewer_rejects_extra_tools_and_blocks_review(self):
        reply = Result(0, json.dumps({"response": "Glob\nGrep\nRead\nmcp__TestSprite__run"}), "")
        with mock.patch.object(zcode_lite, "run", return_value=reply) as r:
            code, text, detail = self.p.run_review("review")
        self.assertEqual(code, 3)
        self.assertIn("mcp__TestSprite__run", detail)
        self.assertEqual(r.call_count, 1)  # the review itself never ran

    def test_run_review_returns_response(self):
        replies = [Result(0, json.dumps({"response": "Read\nGlob\nGrep"}), ""),
                   Result(0, json.dumps({"response": "Reviewer: zcode at t\nPASS"}), "")]
        with mock.patch.object(zcode_lite, "run", side_effect=replies) as r:
            code, text, _ = self.p.run_review("review T9")
        self.assertEqual((code, text), (0, "Reviewer: zcode at t\nPASS"))
        self.assertEqual(r.call_args.kwargs["env"]["ZCODE_DATA_BASE_DIR"], str(paths.ZCODE_HOME))

    # disconnect: official logout in the isolated home only
    def test_disconnect(self):
        self.assertIn("not affected", self.p.disconnect_warning())
        with mock.patch.object(zcode_lite, "run",
                               return_value=Result(0, '{"status":"logged_out","provider":"zai"}', "")) as r:
            st = self.p.disconnect()
        self.assertEqual(st.state, State.NOT_CONNECTED)
        self.assertEqual(r.call_args.args[0][-2:], ["logout", "--json"])
        self.assertEqual(r.call_args.kwargs["env"]["ZCODE_DATA_BASE_DIR"], str(paths.ZCODE_HOME))


if __name__ == "__main__":
    unittest.main()
