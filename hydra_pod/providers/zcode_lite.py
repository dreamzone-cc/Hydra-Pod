"""ZCode Lite: GLM-5.3 on the Z.ai GLM Coding Plan through the official ZCode CLI.

Every step delegates to the official `zcode.cjs` extracted from the installed
ZCode app (runtime/zcode.py), in the isolated ZCODE_DATA_BASE_DIR:
- connect:    `zcode login zai --json` (browser OAuth; ZCode handles the
              callback, polling and session storage itself)
- test:       `zcode -p "Reply with exactly: OK" --json` with every tool removed
- disconnect: `zcode logout --json` (isolated session only)

We never open, parse or copy ZCode's session files. `status()` only checks
whether the session file exists (no read) and reuses the last live result.
"""

import json
import subprocess
import sys
import time

from .. import paths, state_store
from ..runtime import zcode as zrt
from ..runtime.proc import run
from ..status import ProviderStatus, State, classify_failure
from .base import Provider

LOGIN_TIMEOUT_S = 330      # ZCode's flow expires after ~299 s; allow a little slack
EARLY_FAILURE_S = 30       # failing faster than this means the flow never started
EARLY_RETRIES = 3
TEST_TIMEOUT_S = 180

# Every tool of CLI 0.16.9 (docs/10, section 0-6): the connection test needs none.
ALL_TOOLS = (
    "Read Glob Grep TodoRead TodoWrite ReadSessionContext Write Edit Bash "
    "js js_reset js_add_node_module_dir mcp__node_repl__js mcp__node_repl__js_reset "
    "mcp__node_repl__js_add_node_module_dir Agent EvalWorkflowSnippet CreateWorkflow "
    "AmendWorkflow SaveWorkflow ResumeWorkflowRun ResolveWorkflowQuestion GetWorkflowRun "
    "ListWorkflowRuns ListSavedWorkflows CronCreate CronUpdate CronDelete CronList "
    "OffPeakCreate OffPeakList TaskStop TaskOutput SendMessage RespondToCoordinator "
    "submit_result escalate ExitPlanMode EnterPlanMode WebFetch WebSearch AskUserQuestion Skill "
    "ListModels"
)

# Reviewer role: only these tools remain. Everything else is removed with
# --disallowed-tools, which drops tools before the session starts (stronger
# than a permission prompt). MCP is switched off through a project config in a
# private review folder, because user-level MCP servers (e.g. TestSprite, which
# can execute code) would otherwise appear with names no static list can predict.
REVIEW_TOOLS = ("Read", "Glob", "Grep")
REVIEW_DISALLOWED = " ".join(t for t in ALL_TOOLS.split() if t not in REVIEW_TOOLS)
REVIEW_TIMEOUT_S = 1200


class ZCodeLite(Provider):
    def _runtime(self) -> zrt.Runtime:
        rt = zrt.installed()
        if rt is None:
            rt = zrt.install()
        return rt

    def _session_mtime(self) -> float | None:
        # stat() only; the session file is never opened.
        try:
            return (paths.ZCODE_HOME / ".zcode" / "v2" / "credentials.json").stat().st_mtime
        except OSError:
            return None

    def _status(self, state: State, detail: str = "", verified: bool = False,
                model: str | None = None) -> ProviderStatus:
        return ProviderStatus(self.id, state, detail=detail, verified=verified,
                              model=model or self.spec.get("expected_model"))

    def status(self) -> ProviderStatus:
        mtime = self._session_mtime()
        if mtime is None:
            return self._status(State.NOT_CONNECTED, "no login in the isolated ZCode home",
                                verified=True)
        last = state_store.load().get(self.id)
        # A verified result is reused only if the session has not changed since.
        if last and last.verified and last.checked_at >= mtime:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(last.checked_at))
            last.verified = False
            last.detail = (last.detail + "; " if last.detail else "") + f"as of live check {when}"
            return last
        return self._status(State.CONNECTED, "session changed since last check; run `test` to verify")

    def test(self) -> ProviderStatus:
        rt = self._runtime()
        probe = paths.CACHE_DIR / "zcode-probe"
        probe.mkdir(parents=True, exist_ok=True)
        r = run(zrt.command(rt, "-p", "Reply with exactly: OK", "--json",
                            "--disallowed-tools", ALL_TOOLS, "--cwd", str(probe)),
                env=zrt.env(), cwd=str(probe), timeout=TEST_TIMEOUT_S)
        if r.code == 0:
            try:
                resp = str(json.loads(r.stdout).get("response", "")).strip()
            except ValueError:
                resp = ""
            if resp.upper().startswith("OK"):
                return self._status(State.CONNECTED, "live call succeeded", verified=True)
            return self._status(State.AUTH_FAILED, f"unexpected reply: {resp[:80]!r}", verified=True)
        if r.timed_out:
            return self._status(State.AUTH_FAILED, "test call timed out", verified=True)
        state, detail = classify_failure(r.stderr + "\n" + r.stdout)
        return self._status(state, detail, verified=True)

    def connect(self, *, open_browser: bool = True, method: str | None = None) -> ProviderStatus:
        rt = self._runtime()
        state_store.save(self._status(State.AUTHENTICATING, "waiting for browser approval"))
        args = ["login", self.spec.get("login_target", "zai"), "--json"]
        if not open_browser:
            args.append("--no-browser")
        print("Approve in the browser now: the authorization expires after about 5 minutes.\n"
              "Close any older chat.z.ai / zcode.z.ai tabs first.", file=sys.stderr)
        # stderr stays attached so the user sees the official URL/messages;
        # stdout (the JSON result, which includes account details) is captured.
        # ZCode's flow start (oauth/cli/init) intermittently fails within seconds with
        # "fetch failed"; a failure that fast never reached the browser, so retry it.
        for attempt in range(1, EARLY_RETRIES + 1):
            started = time.time()
            try:
                p = subprocess.run(zrt.command(rt, *args), env=zrt.env(), stdout=subprocess.PIPE,
                                   stdin=subprocess.DEVNULL, text=True, timeout=LOGIN_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                return self._status(State.AUTH_FAILED, "authorization timed out", verified=True)
            took = int(time.time() - started)
            if p.returncode == 0 or took >= EARLY_FAILURE_S:
                break
            print(f"Flow start failed after {took}s (attempt {attempt}/{EARLY_RETRIES}); retrying...",
                  file=sys.stderr)
            time.sleep(3)
        if p.returncode != 0:
            return self._status(State.AUTH_FAILED, f"official login failed after {took}s", verified=True)
        try:
            result = json.loads(p.stdout)
        except ValueError:
            return self._status(State.AUTH_FAILED, "login returned no JSON", verified=True)
        if result.get("status") != "ready":
            return self._status(State.AUTH_FAILED, f"login status {result.get('status')!r}",
                                verified=True)
        model = result.get("model")
        print(f"Authorized after {took}s; model {model}. Verifying with a live call...",
              file=sys.stderr)
        st = self.test()
        st.model = model or st.model
        if model and self.spec.get("expected_model") and model != self.spec["expected_model"]:
            st.detail += f"; note: model differs from expected {self.spec['expected_model']}"
        return st

    # ---- reviewer role -------------------------------------------------

    def review_dir(self):
        """Private working folder for reviews; its project config disables MCP."""
        d = paths.CACHE_DIR / "zcode-review"
        (d / ".zcode").mkdir(parents=True, exist_ok=True)
        (d / ".zcode" / "config.json").write_text('{\n  "features": { "mcp": false }\n}\n')
        return d

    def worker_command(self, role: str, prompt: str, cwd: str | None = None) -> list[str]:
        if role != "reviewer":
            raise NotImplementedError(f"{self.id}: only the reviewer role is supported")
        d = self.review_dir()
        return zrt.command(self._runtime(), "-p", prompt, "--mode", "yolo",
                           "--disallowed-tools", REVIEW_DISALLOWED, "--json", "--cwd", str(d))

    def review_tools(self) -> list[str] | None:
        """Ask the restricted session which tools it can call (a live, cheap call)."""
        argv = self.worker_command("reviewer", "List the exact names of every tool you can "
                                   "call right now, one per line, nothing else.")
        r = run(argv, env=zrt.env(), cwd=str(self.review_dir()), timeout=TEST_TIMEOUT_S)
        if r.code != 0:
            return None
        try:
            text = str(json.loads(r.stdout).get("response", ""))
        except ValueError:
            return None
        return sorted(line.strip(" -*`") for line in text.splitlines() if line.strip())

    def verify_reviewer(self) -> tuple[bool, str]:
        """Confirm the reviewer sees exactly REVIEW_TOOLS; cached per ZCode runtime."""
        rt = self._runtime()
        marker = paths.CACHE_DIR / f"zcode-review-verified-{rt.app_version}-{rt.entry_sha256[:12]}"
        if marker.exists():
            return True, "tool set verified for this ZCode runtime"
        tools = self.review_tools()
        if tools is None:
            return False, "could not list reviewer tools"
        if tools != sorted(REVIEW_TOOLS):
            return False, f"unexpected reviewer tools: {', '.join(tools)}"
        marker.write_text(" ".join(tools) + "\n")
        return True, "tool set verified: " + ", ".join(tools)

    def run_review(self, prompt: str) -> tuple[int, str, str]:
        """Run one read-only review; returns (exit code, response text, detail).

        Usage figures of the last run (tokens, model requests) are kept in
        self.last_usage for cost logging."""
        self.last_usage = None
        ok, why = self.verify_reviewer()
        if not ok:
            return 3, "", f"reviewer not safe to run: {why}"
        r = run(self.worker_command("reviewer", prompt), env=zrt.env(),
                cwd=str(self.review_dir()), timeout=REVIEW_TIMEOUT_S)
        if r.code != 0:
            state, detail = classify_failure(r.stderr + "\n" + r.stdout)
            return r.code or 1, "", f"{state.value}: {detail}"
        try:
            result = json.loads(r.stdout)
        except ValueError:
            return 1, "", "review returned no JSON"
        usage = result.get("usage") or {}
        self.last_usage = {k: usage.get(k) for k in
                           ("modelRequestCount", "inputTokens", "outputTokens", "reasoningTokens",
                            "cacheReadTokens", "totalTokens")}
        return 0, str(result.get("response", "")), why

    def disconnect_warning(self) -> str:
        return ("This signs out the Hydra-Pod ZCode session in "
                f"{paths.ZCODE_HOME}. The ZCode desktop app keeps its own login and is not affected.")

    def disconnect(self) -> ProviderStatus:
        rt = self._runtime()
        r = run(zrt.command(rt, "logout", "--json"), env=zrt.env(), timeout=60)
        try:
            logged_out = r.code == 0 and json.loads(r.stdout).get("status") == "logged_out"
        except ValueError:
            logged_out = False
        if logged_out:
            return self._status(State.NOT_CONNECTED, "logged out (isolated session)", verified=True)
        state, detail = classify_failure(r.stderr + "\n" + r.stdout)
        return self._status(State.AUTH_FAILED, f"logout failed: {detail}", verified=True)
