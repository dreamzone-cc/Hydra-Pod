"""OpenCode Go (DeepSeek V4.1 Flash) through the official opencode CLI.

Two official ways to authorize, both delegated to opencode itself:
- device (default): `opencode auth login opencode --method device` prints a code
  and a URL on opencode.ai/console/device and opens the browser; opencode
  stores the "OpenCode Console" login. Verified on 2026-09-26: with only this
  login and no Go key, `opencode-go/deepseek-v4.1-flash` answers.
- key: `opencode auth login opencode-go --method key` (needs a real terminal;
  the key is typed into opencode's own prompt).

The model is always `opencode-go/...` (Go endpoint). Never `opencode/...`,
which bills the separate Zen balance. Hydra-Pod never sees a key or
token; it reads only provider and credential labels from `opencode auth list`.

Every opencode call closes stdin: `opencode run` waits for stdin when it is
not a terminal, which is what looked like "startup stalls" earlier.
"""

import json
import os
import re
import subprocess
import sys
import time

from .. import state_store
from ..runtime.proc import run, run_attached
from ..status import ProviderStatus, State, classify_failure
from .base import Provider

TEST_TIMEOUT_S = 120
DEVICE_TIMEOUT_S = 600    # device codes observed to expire after ~10 minutes
URL_RE = re.compile(r"https://opencode\.ai/console/device\?\S+")
CODE_RE = re.compile(r"Enter code:\s*([A-Z0-9-]+)")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _last_text(jsonl: str) -> str:
    text = ""
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "text":
            text = (event.get("part") or {}).get("text", text)
    return text


class OpenCodeProvider(Provider):
    @property
    def oc_provider(self) -> str:
        return self.spec["opencode_provider"]

    def _status(self, state: State, detail: str = "", verified: bool = False) -> ProviderStatus:
        return ProviderStatus(self.id, state, detail=detail, verified=verified,
                              model=self.spec.get("model"))

    def _logins(self) -> dict[str, list[str]] | None:
        """{provider label: [credential labels]} from `opencode auth list` (no secrets)."""
        r = run(["opencode", "auth", "list"], timeout=30)
        if r.code != 0:
            return None
        found: dict[str, list[str]] = {}
        for line in r.stdout.splitlines():
            cols = re.split(r"\s{2,}", line.strip())
            if len(cols) > 1:
                found.setdefault(cols[0], []).append(cols[1])
        return found

    def _our_logins(self) -> dict[str, tuple[str, list[str]]] | None:
        """Logins that can serve this provider: {method: (opencode provider id, credentials)}."""
        logins = self._logins()
        if logins is None:
            return None
        ours = {}
        key_label = self.spec.get("auth_list_label", "OpenCode Go")
        if logins.get(key_label):
            ours["key"] = (self.oc_provider, logins[key_label])
        dev_label = self.spec.get("device_list_label")
        if dev_label and logins.get(dev_label):
            ours["device"] = (self.spec["device_provider"], logins[dev_label])
        return ours

    def status(self) -> ProviderStatus:
        ours = self._our_logins()
        if ours is None:
            return self._status(State.AUTH_FAILED, "`opencode auth list` failed")
        if not ours:
            return self._status(State.NOT_CONNECTED, "no OpenCode Go key or OpenCode Console login",
                                verified=True)
        how = " + ".join(sorted(ours))
        last = state_store.load().get(self.id)
        if last and last.verified and last.state != State.NOT_CONNECTED:
            last.verified = False
            last.detail = f"{last.detail}; via {how}; as of last live check"
            return last
        return self._status(State.CONNECTED, f"login present via {how}; run `test` to verify")

    def test(self) -> ProviderStatus:
        # proc.run closes stdin, so `opencode run` does not wait for it.
        r = run(["opencode", "run", "--standalone", "--format", "json",
                 "-m", self.spec["model"], "Reply with exactly: OK"], timeout=TEST_TIMEOUT_S)
        text = _last_text(r.stdout).strip()
        if r.code == 0 and text.upper().startswith("OK"):
            return self._status(State.CONNECTED, "live call succeeded", verified=True)
        if r.timed_out:
            return self._status(State.AUTH_FAILED, "test call timed out", verified=True)
        out = r.stdout + "\n" + r.stderr
        if "Model unavailable" in out:
            return self._status(State.NOT_CONNECTED, "model unavailable: no usable login",
                                verified=True)
        state, detail = classify_failure(out)
        return self._status(state, detail, verified=True)

    def connect(self, *, open_browser: bool = True, method: str | None = None) -> ProviderStatus:
        method = method or self.spec.get("auth_methods", ["key"])[0]
        if method == "device":
            return self._connect_device(open_browser)
        if method == "key":
            return self._connect_key(open_browser)
        return self._status(State.AUTH_FAILED, f"unsupported method {method!r}")

    def _connect_device(self, open_browser: bool) -> ProviderStatus:
        state_store.save(self._status(State.AUTHENTICATING, "waiting for browser approval"))
        env = dict(os.environ)
        if not open_browser:
            env["BROWSER"] = "true"   # opencode then only prints the URL
        argv = ["opencode", "auth", "login", self.spec["device_provider"],
                "--method", "device", "--standalone"]
        p = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
        shown_code = shown_url = False
        deadline = time.time() + DEVICE_TIMEOUT_S
        try:
            for raw in p.stdout:
                line = ANSI_RE.sub("", raw)
                code, url = CODE_RE.search(line), URL_RE.search(line)
                if code and not shown_code:
                    print(f"Code: {code.group(1)}", file=sys.stderr)
                    shown_code = True
                if url and not shown_url:
                    print(f"Approve at: {url.group(0)}\n"
                          "(opened in your browser; the code expires after about 10 minutes)",
                          file=sys.stderr)
                    shown_url = True
                if time.time() > deadline:
                    p.kill()
                    break
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        if p.returncode != 0 or not (self._our_logins() or {}).get("device"):
            return self._status(State.AUTH_FAILED, "device authorization not completed",
                                verified=True)
        print("Authorized. Verifying with a live call...", file=sys.stderr)
        return self.test()

    def _connect_key(self, open_browser: bool) -> ProviderStatus:
        if not sys.stdin.isatty():
            st = self.status()
            st.detail = ("key method needs an interactive terminal: run "
                         f"`hydra-pod-connect connect {self.id} --method key` in a terminal; "
                         f"current: {st.detail}")
            return st
        page = self.spec.get("key_page")
        if page:
            print(f"Get your key at {page} (subscribe to Go, then copy the API key).",
                  file=sys.stderr)
            if open_browser:
                import webbrowser
                webbrowser.open(page)
        print("Paste the key into opencode's own prompt; Hydra-Pod never sees it.",
              file=sys.stderr)
        state_store.save(self._status(State.AUTHENTICATING, "waiting for the official key prompt"))
        code = run_attached(["opencode", "auth", "login", self.oc_provider, "--method", "key"])
        if code != 0 or not (self._our_logins() or {}).get("key"):
            return self._status(State.AUTH_FAILED, f"official key login exited with {code}",
                                verified=True)
        print("Key stored. Verifying with a live call...", file=sys.stderr)
        return self.test()

    def disconnect_warning(self) -> str:
        return ("This removes the OpenCode Go key and the OpenCode Console login from opencode "
                "itself. Every opencode tool using them (including the Hydra-Pod builder) "
                "stops working until you connect again.")

    def disconnect(self) -> ProviderStatus:
        ours = self._our_logins()
        if ours is None:
            return self._status(State.AUTH_FAILED, "`opencode auth list` failed")
        if not ours:
            return self._status(State.NOT_CONNECTED, "nothing to remove", verified=True)
        for provider_id, creds in ours.values():
            for cred in creds:
                # Naming the credential skips the account picker, so no TTY is needed.
                r = run(["opencode", "auth", "logout", provider_id, cred, "--standalone"],
                        timeout=60)
                if r.code != 0:
                    return self._status(State.AUTH_FAILED,
                                        f"official logout failed for {provider_id}/{cred}",
                                        verified=True)
        if not self._our_logins():
            return self._status(State.NOT_CONNECTED, "logins removed from opencode", verified=True)
        return self._status(State.AUTH_FAILED, "a login is still listed after logout",
                            verified=True)
