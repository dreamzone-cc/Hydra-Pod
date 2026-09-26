"""hydra-pod-connect: connect accounts to AI providers through their official tools.

  hydra-pod-connect list                     providers and their last known state
  hydra-pod-connect status [PROVIDER]        state without spending quota
  hydra-pod-connect test PROVIDER            one minimal live call
  hydra-pod-connect connect PROVIDER [--no-browser] [--method device|key]
  hydra-pod-connect disconnect PROVIDER [--yes]
  hydra-pod-connect review PROVIDER --prompt-file F [--out REPORT.md]   read-only review
  hydra-pod-connect runtime info|install [--force]   official ZCode CLI runtime
"""

import argparse
import json
import sys

from . import paths, state_store
from .providers import registry
from .runtime import zcode as zcode_rt
from .status import ProviderStatus, State

ICON = {State.CONNECTED: "●", State.AUTHENTICATING: "…", State.NOT_CONNECTED: "○",
        State.AUTH_FAILED: "✗", State.EXPIRED: "!"}


def _line(p, st: ProviderStatus) -> str:
    extra = f" · {st.model}" if st.model else ""
    detail = f" · {st.detail}" if st.detail else ""
    live = "" if st.verified else " (unverified)"
    return f"{ICON[st.state]} {p.id:<12} {st.state.value}{live}{extra}{detail}"


def cmd_list(a) -> int:
    cached = state_store.load()
    for p in registry.all_providers():
        st = cached.get(p.id) or ProviderStatus(p.id, State.NOT_CONNECTED, detail="never checked")
        print(_line(p, st) + f"\n    {p.display_name}")
    return 0


def _record(p, st: ProviderStatus, as_json: bool) -> int:
    # Only live (verified) results are cached; a status inferred from the cache
    # must not overwrite the live result it was derived from.
    if st.verified or st.state == State.AUTHENTICATING:
        state_store.save(st)
    print(json.dumps(st.to_dict(), indent=2) if as_json else _line(p, st))
    return 0 if st.state == State.CONNECTED else 1


def cmd_status(a) -> int:
    targets = [registry.get(a.provider)] if a.provider else registry.all_providers()
    rc = 0
    for p in targets:
        rc |= _record(p, p.status(), a.json)
    return rc


def cmd_test(a) -> int:
    p = registry.get(a.provider)
    return _record(p, p.test(), a.json)


def cmd_connect(a) -> int:
    p = registry.get(a.provider)
    print(f"Connecting {p.display_name} through its official login.", file=sys.stderr)
    kwargs = {"method": a.method} if a.method else {}
    return _record(p, p.connect(open_browser=not a.no_browser, **kwargs), a.json)


def cmd_disconnect(a) -> int:
    p = registry.get(a.provider)
    warning = p.disconnect_warning()
    if warning and not a.yes:
        print(f"WARNING: {warning}", file=sys.stderr)
        if not sys.stdin.isatty():
            print("refusing without --yes in non-interactive mode", file=sys.stderr)
            return 2
        if input("Type 'disconnect' to continue: ").strip() != "disconnect":
            print("cancelled", file=sys.stderr)
            return 2
    return _record_disconnect(p, a.json)


def _record_disconnect(p, as_json: bool) -> int:
    st = p.disconnect()
    state_store.save(st)
    print(json.dumps(st.to_dict(), indent=2) if as_json else _line(p, st))
    return 0 if st.state == State.NOT_CONNECTED else 1


def cmd_review(a) -> int:
    p = registry.get(a.provider)
    if not hasattr(p, "run_review"):
        print(f"{p.id} has no reviewer role", file=sys.stderr)
        return 2
    prompt = open(a.prompt_file, encoding="utf-8").read()
    code, text, detail = p.run_review(prompt)
    print(detail, file=sys.stderr)
    if code == 0:
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(text.rstrip() + "\n")
        else:
            print(text)
    return code


def cmd_runtime(a) -> int:
    if a.action == "install":
        rt = zcode_rt.install(force=a.force)
    else:
        rt = zcode_rt.installed()
        if rt is None:
            src = zcode_rt.find_appimage()
            print(f"not installed; source app: {src or 'not found'}\n"
                  f"run: hydra-pod-connect runtime install", file=sys.stderr)
            return 1
    print(json.dumps({**rt.__dict__, "zcode_home": str(paths.ZCODE_HOME)}, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hydra-pod-connect", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    s = sub.add_parser("status"); s.add_argument("provider", nargs="?"); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_status)
    t = sub.add_parser("test"); t.add_argument("provider"); t.add_argument("--json", action="store_true"); t.set_defaults(fn=cmd_test)
    c = sub.add_parser("connect"); c.add_argument("provider"); c.add_argument("--no-browser", action="store_true"); c.add_argument("--method", choices=["device", "key"]); c.add_argument("--json", action="store_true"); c.set_defaults(fn=cmd_connect)
    d = sub.add_parser("disconnect"); d.add_argument("provider"); d.add_argument("--yes", action="store_true"); d.add_argument("--json", action="store_true"); d.set_defaults(fn=cmd_disconnect)
    v = sub.add_parser("review", help="run one read-only review with a reviewer provider"); v.add_argument("provider"); v.add_argument("--prompt-file", required=True); v.add_argument("--out"); v.set_defaults(fn=cmd_review)
    r = sub.add_parser("runtime"); r.add_argument("action", choices=["info", "install"]); r.add_argument("--force", action="store_true"); r.set_defaults(fn=cmd_runtime)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except KeyError as e:
        print(str(e).strip("'\""), file=sys.stderr)
        return 2
