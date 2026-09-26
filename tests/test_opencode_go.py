import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hydra_pod import paths
from hydra_pod.providers import opencode_go, registry
from hydra_pod.runtime.proc import Result
from hydra_pod.status import State

KEY = "OpenCode Go       API key                     stored\n"
CONSOLE = "OpenCode Console  Default                     stored\n"
OTHER = "OpenRouter        API key                     stored\n"


def events(text):
    return "\n".join([json.dumps({"type": "step_start"}),
                      json.dumps({"type": "text", "part": {"text": text}})])


class FakePopen:
    def __init__(self, lines, code=0):
        self.stdout = io.StringIO("".join(lines))
        self.returncode = code

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass


class OpenCodeGoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.patches = [mock.patch.object(paths, "CACHE_DIR", d),
                        mock.patch.object(paths, "STATUS_CACHE", d / "s.json"),
                        # Safety net: no test may ever start a real opencode process.
                        mock.patch.object(opencode_go.subprocess, "Popen",
                                          side_effect=AssertionError("real Popen in test")),
                        mock.patch.object(opencode_go, "run_attached",
                                          side_effect=AssertionError("real attached run in test"))]
        for p in self.patches:
            p.start()
        self.p = registry.get("opencode-go")

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_spec(self):
        self.assertIsInstance(self.p, opencode_go.OpenCodeProvider)
        self.assertEqual(self.p.spec["auth_methods"][0], "device")
        self.assertEqual(self.p.spec["model"], "opencode-go/deepseek-v4.1-flash")

    def test_status_recognises_key_console_or_none(self):
        for listing, state, how in ((OTHER, State.NOT_CONNECTED, None),
                                    (KEY + OTHER, State.CONNECTED, "key"),
                                    (CONSOLE, State.CONNECTED, "device"),
                                    (KEY + CONSOLE, State.CONNECTED, "device + key")):
            with self.subTest(how=how), mock.patch.object(opencode_go, "run",
                                                          return_value=Result(0, listing, "")):
                st = self.p.status()
                self.assertEqual(st.state, state)
                if how:
                    self.assertIn(how, st.detail)

    def test_exact_label_match(self):
        with mock.patch.object(opencode_go, "run",
                               return_value=Result(0, "OpenCode Go Legacy  x  stored\n", "")):
            self.assertEqual(self.p.status().state, State.NOT_CONNECTED)

    def test_live_call_go_endpoint_only(self):
        with mock.patch.object(opencode_go, "run", return_value=Result(0, events("OK"), "")) as r:
            self.assertEqual(self.p.test().state, State.CONNECTED)
        argv = r.call_args.args[0]
        self.assertEqual(argv[:5], ["opencode", "run", "--standalone", "--format", "json"])
        self.assertIn("opencode-go/deepseek-v4.1-flash", argv)
        self.assertFalse(any(a.startswith("opencode/") for a in argv))  # Zen balance, never

    def test_model_unavailable_means_not_connected(self):
        out = json.dumps({"type": "error", "message": "Model unavailable: opencode-go/deepseek-v4.1-flash"})
        with mock.patch.object(opencode_go, "run", return_value=Result(1, out, "")):
            self.assertEqual(self.p.test().state, State.NOT_CONNECTED)

    def test_device_connect_shows_code_url_then_verifies(self):
        fake = FakePopen(["◇  Authorization started\n", "●  Enter code: ABCD-EFGH\n",
                          "●  https://opencode.ai/console/device?user_code=ABCD-EFGH&client_id=opencode-cli\n",
                          "◇  Connected to OpenCode Console\n"])
        err = io.StringIO()
        with mock.patch.object(opencode_go.subprocess, "Popen", return_value=fake) as po, \
             mock.patch.object(opencode_go, "run",
                               side_effect=[Result(0, CONSOLE, ""), Result(0, events("OK"), "")]), \
             mock.patch("sys.stderr", err):
            st = self.p.connect(open_browser=False)
        argv, kw = po.call_args.args[0], po.call_args.kwargs
        self.assertEqual(argv, ["opencode", "auth", "login", "opencode", "--method", "device",
                                "--standalone"])
        self.assertEqual(kw["stdin"], subprocess.DEVNULL)
        self.assertEqual(kw["env"]["BROWSER"], "true")
        self.assertIn("ABCD-EFGH", err.getvalue())
        self.assertIn("opencode.ai/console/device", err.getvalue())
        self.assertEqual(st.state, State.CONNECTED)

    def test_device_connect_failure(self):
        with mock.patch.object(opencode_go.subprocess, "Popen", return_value=FakePopen(["Failed\n"], 1)), \
             mock.patch.object(opencode_go, "run", return_value=Result(0, OTHER, "")), \
             mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(self.p.connect().state, State.AUTH_FAILED)

    def test_key_connect_requires_terminal(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=False), \
             mock.patch.object(opencode_go, "run", return_value=Result(0, KEY, "")):
            st = self.p.connect(method="key")
        self.assertEqual(st.state, State.CONNECTED)
        self.assertIn("interactive terminal", st.detail)

    def test_disconnect_removes_key_and_console_by_name(self):
        after = Result(0, OTHER, "")
        with mock.patch.object(opencode_go, "run",
                               side_effect=[Result(0, KEY + CONSOLE, ""), Result(0, "ok", ""),
                                            Result(0, "ok", ""), after]) as r:
            st = self.p.disconnect()
        self.assertEqual(st.state, State.NOT_CONNECTED)
        calls = [c.args[0] for c in r.call_args_list[1:3]]
        self.assertIn(["opencode", "auth", "logout", "opencode-go", "API key", "--standalone"], calls)
        self.assertIn(["opencode", "auth", "logout", "opencode", "Default", "--standalone"], calls)

    def test_disconnect_warning_mentions_both(self):
        w = self.p.disconnect_warning()
        self.assertIn("OpenCode Go key", w)
        self.assertIn("OpenCode Console", w)


if __name__ == "__main__":
    unittest.main()
