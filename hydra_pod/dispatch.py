"""hydra-pod-dispatch: the mechanical steps between layers (recommendation R3, docs/11).

Judgment stays with the manager (writing tickets, validating findings,
writing fix tickets). This module does only what can be checked:

  claim   open -> doing, record base = HEAD, sign claimed-by, commit
  build   account gate, run the builder through the watchdog, check the receipt
          and that only allowed_files changed
  accept  rerun every acceptance command (stdin closed), check scope, commit the
          work, record head, state -> review
  review  account gate, render the reviewer prompt from the header (R1 context
          block filled), run it, save the report, list its PROBE lines
  probes  run the report's PROBE lines at head (scripts/probe-run.py)
  close   state -> done, doing -> done, commit
  status  table of every ticket; writes _tickets/STATE.md
  preflight  everything a ticket needs before it starts (R5); claim runs it
  costs   per-run cost log of a ticket or of all tickets (R6)

Every command prints what it did and exits non-zero on the first failed check.
Set HYDRA_POD_COMMIT_TRAILER (legacy name OM_COMMIT_TRAILER) to append a trailer
(e.g. a Co-Authored-By line) to commits.
"""

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import quota, ticket as tk
from .providers import registry
from .runtime.proc import run
from .status import State

REPO = Path(__file__).resolve().parents[1]
PROMPTS = REPO / "prompts"
RECEIPT_TEMPLATE = Path.home() / ".claude/skills/opus-manager/templates/receipt.md"


class Abort(Exception):
    pass


# ---- helpers -------------------------------------------------------------

def git(project: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    if check and r.returncode != 0:
        raise Abort(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def env_or_legacy(new: str, legacy: str, default: str = "") -> str:
    """Value of the new variable, else its legacy name, else <default>."""
    value = os.environ.get(new)
    if value is not None:  # a set new variable wins even when it is empty
        return value
    return os.environ.get(legacy, default)  # legacy name fallback


def commit(project: Path, message: str, paths: list[str]) -> str:
    git(project, "add", "--", *paths)
    trailer = env_or_legacy("HYDRA_POD_COMMIT_TRAILER", "OM_COMMIT_TRAILER").strip()  # legacy name
    args = ["commit", "-q", "-m", message] + (["-m", trailer] if trailer else [])
    git(project, *args)
    return git(project, "rev-parse", "--short", "HEAD")


def template_block(name: str) -> str:
    text = (PROMPTS / name).read_text(encoding="utf-8")
    m = re.search(r"^```text\n(.*?)^```", text, re.S | re.M)
    if not m:
        raise Abort(f"no ```text block in prompts/{name}")
    return m.group(1).rstrip("\n")


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def changed_files(project: Path, base: str) -> set[str]:
    tracked = git(project, "diff", "--name-only", base).splitlines()
    untracked = git(project, "ls-files", "--others", "--exclude-standard").splitlines()
    return {p for p in tracked + untracked if p}


def out_of_scope(t: tk.Ticket, files: set[str]) -> list[str]:
    """Changed files the worker was not allowed to touch.

    Manager-owned paths are ignored: this ticket's own file, the generated
    _tickets/STATE.md, and _receipts/ (this ticket's records, and other tickets'
    records the manager may still have uncommitted)."""
    own = {f"_tickets/{f}/{t.id}.md" for f in ("open", "doing", "done")} | {"_tickets/STATE.md"}
    allowed = set(t.allowed_files)
    return sorted(f for f in files
                  if f not in allowed and f not in own and not f.startswith("_receipts/"))


def jsonl_metrics(path: Path) -> dict:
    """Duration, tool calls, denied calls, tokens and opencode's catalog-price estimate."""
    ts, tools, denied, cost = [], 0, 0, 0.0
    tok = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0}
    if path.is_file():
        for line in path.read_text(errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("timestamp"):
                ts.append(e["timestamp"])
            part = e.get("part") or {}
            if e.get("type") == "tool_use":
                tools += 1
                denied += part.get("state", {}).get("status") == "error"
            if e.get("type") == "step_finish":
                t = part.get("tokens") or {}
                tok["input"] += int(t.get("input") or 0)
                tok["output"] += int(t.get("output") or 0)
                tok["reasoning"] += int(t.get("reasoning") or 0)
                tok["cache_read"] += int((t.get("cache") or {}).get("read") or 0)
                cost += float(part.get("cost") or 0)
    secs = round((max(ts) - min(ts)) / 1000) if len(ts) > 1 else None
    return {"seconds": secs, "tool_calls": tools, "denied": denied, "tokens": tok,
            "list_cost_usd": round(cost, 6)}


def record_cost(project: Path, tid: str, entry: dict) -> None:
    """Append one run to _receipts/<ticket>.costs.jsonl (R6)."""
    entry = {"at": now_iso(), **entry}
    with open(project / "_receipts" / f"{tid}.costs.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def watchdog(project: Path) -> str:
    local = project / "_tickets" / "run-watchdog.sh"
    return str(local if local.is_file() else REPO / "templates/project/_tickets/run-watchdog.sh")


CONNECT_HINT = ("in a separate terminal window run `hydra-pod-connect connect {p}` and approve in the "
                "browser right away (zcode-lite expires after ~5 minutes)")


def provider_problem(provider_id: str) -> str | None:
    st = registry.get(provider_id).status()
    if st.state != State.CONNECTED:
        return f"{provider_id} is {st.state.value} ({st.detail}); " + CONNECT_HINT.format(p=provider_id)
    return None


def opencode_label_problem(label: str, how: str) -> str | None:
    r = run(["opencode", "auth", "list"], timeout=30)
    names = [re.split(r"\s{2,}", l.strip())[0] for l in r.stdout.splitlines() if l.strip()]
    return None if label in names else f"opencode has no '{label}' login; {how}"


def gate_provider(provider_id: str) -> None:
    problem = provider_problem(provider_id)
    if problem:
        raise Abort(problem)


def gate_opencode_label(label: str) -> None:
    problem = opencode_label_problem(label, "run `opencode auth login zai-coding-plan` in a terminal")
    if problem:
        raise Abort(problem)


MIN_ZAI_CREDITS = int(env_or_legacy("HYDRA_POD_MIN_ZAI_CREDITS", "OM_MIN_ZAI_CREDITS", "100"))  # legacy name


def preflight_checks(project: Path, t: tk.Ticket) -> list[tuple[str, bool | None, str]]:
    """(check, ok, detail); ok None = warning only. Spends no model quota."""
    checks = []
    problems = t.validate()
    checks.append(("ticket header", not problems, "; ".join(problems)))
    dirty = git(project, "status", "--porcelain", "--untracked-files=no", check=False)
    checks.append(("working tree clean", not dirty, "uncommitted changes" if dirty else ""))
    worker = t.header.get("worker", "opencode-go/deepseek-v4.1-flash")
    if worker.startswith("opencode-go/"):
        p = provider_problem("opencode-go")
        checks.append(("builder account (opencode-go)", p is None, p or ""))
    uses_zai = False
    for rv in t.reviewers:
        if rv == "opencode":
            p = opencode_label_problem("Z.AI Coding Plan", "run `opencode auth login zai-coding-plan` in a terminal")
            checks.append(("reviewer account (opencode / Z.AI Coding Plan)", p is None, p or ""))
            uses_zai = True
        elif rv == "zcode":
            p = provider_problem("zcode-lite")
            checks.append(("reviewer account (zcode-lite)", p is None, p or ""))
            uses_zai = True
        else:
            checks.append((f"reviewer {rv!r}", False, "unknown reviewer (opencode | zcode)"))
    if uses_zai:
        q = quota.zai_quota()
        left = quota.min_remaining(q)
        if left is None:
            checks.append(("Z.ai credits", None, "quota unknown (no key file or no answer); not blocking"))
        else:
            checks.append((f"Z.ai credits >= {MIN_ZAI_CREDITS}", left >= MIN_ZAI_CREDITS,
                           f"{left} left in the tightest window"))
    return checks


def preflight(project: Path, tid: str, quiet: bool = False) -> None:
    t = tk.find(project, tid)
    checks = preflight_checks(project, t)
    for name, ok, detail in checks:
        if not quiet or ok is not True:
            mark = {True: "ok  ", False: "FAIL", None: "warn"}[ok]
            say(f"  [{mark}] {name}" + (f": {detail}" if detail else ""))
    failed = [n for n, ok, _ in checks if ok is False]
    if failed:
        raise Abort(f"preflight failed for {tid}: " + ", ".join(failed))
    say(f"preflight ok for {tid}")


def require_state(t: tk.Ticket, *states: str) -> None:
    if t.state not in states:
        raise Abort(f"{t.id} is in state {t.state!r}; this step needs {' or '.join(states)}")


def say(msg: str) -> None:
    print(msg, flush=True)


# ---- steps -----------------------------------------------------------------

def claim(project: Path, tid: str, skip_preflight: bool = False) -> None:
    t = tk.find(project, tid)
    require_state(t, "open")
    problems = t.validate()
    if problems:
        raise Abort(f"{tid} header: " + "; ".join(problems))
    rel = str(t.path.relative_to(project))
    if git(project, "ls-files", "--error-unmatch", rel, check=False) == "":
        commit(project, f"{tid}: open ticket", [rel])          # a freshly written ticket
    if not skip_preflight:
        preflight(project, tid, quiet=True)                   # R5: accounts before work starts
    if git(project, "status", "--porcelain", "--untracked-files=no"):
        raise Abort("working tree has uncommitted changes; commit or stash them first")
    base = git(project, "rev-parse", "--short", "HEAD")
    dest = project / "_tickets" / "doing" / t.path.name
    git(project, "mv", str(t.path.relative_to(project)), str(dest.relative_to(project)))
    t.path = dest
    t.header["state"], t.header["base"] = "doing", base
    worker = t.header.get("worker", "opencode-go/deepseek-v4.1-flash")
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    t.body = re.sub(r"^> claimed-by:.*$", f"> claimed-by: opencode / {worker} @ {stamp}",
                    t.body, count=1, flags=re.M)
    t.save()
    sha = commit(project, f"{tid}: claim for opencode / {worker}", [str(dest.relative_to(project))])
    say(f"claimed {tid}: base={base}, commit {sha}")


def build(project: Path, tid: str) -> None:
    t = tk.find(project, tid)
    require_state(t, "doing")
    worker = t.header.get("worker", "opencode-go/deepseek-v4.1-flash")
    if worker.startswith("opencode-go/"):
        gate_provider("opencode-go")
    prompt = template_block("worker.md").replace("<ticket>", tid).replace(
        "~/.claude/skills/opus-manager/templates/receipt.md", str(RECEIPT_TEMPLATE))
    out = project / "_receipts" / f"{tid}.run.jsonl"
    log = project / "_receipts" / f"{tid}.watchdog.log"
    out.parent.mkdir(exist_ok=True)
    say(f"building {tid} with {worker} ...")
    with open(log, "w") as lf:
        rc = subprocess.run([watchdog(project), str(out), "1800", "--", "opencode", "run",
                             "--standalone", "--format", "json", "-m", worker, "--auto", prompt],
                            cwd=project, stdin=subprocess.DEVNULL, stderr=lf).returncode
    m = jsonl_metrics(out)
    record_cost(project, tid, {"phase": "build", "provider": "opencode-go", "model": worker,
                               "exit": rc, **m})
    receipt = project / "_receipts" / f"{tid}.receipt.md"
    extra = out_of_scope(t, changed_files(project, t.header["base"]))
    say(f"builder exit {rc}; {m['seconds']}s, {m['tool_calls']} tool calls, {m['denied']} denied")
    if rc != 0:
        raise Abort(f"builder failed (exit {rc}); see {log.relative_to(project)}")
    if not receipt.is_file():
        raise Abort(f"no receipt at {receipt.relative_to(project)}")
    if extra:
        raise Abort("files changed outside allowed_files: " + ", ".join(extra))
    say(f"receipt present, scope ok. next: hydra-pod-dispatch accept {tid}")


def accept(project: Path, tid: str) -> None:
    t = tk.find(project, tid)
    require_state(t, "doing")
    extra = out_of_scope(t, changed_files(project, t.header["base"]))
    if extra:
        raise Abort("files changed outside allowed_files: " + ", ".join(extra))
    lines, ok = [f"# Acceptance rerun by the manager: {tid}", "", f"> at {now_iso()}", ""], True
    for i, acc in enumerate(t.acceptance, 1):
        r = run(["bash", "-c", acc.command], cwd=str(project), timeout=900)
        passed = r.code == 0 and (acc.expect is None or acc.expect in r.stdout)
        ok &= passed
        say(f"  [{'PASS' if passed else 'FAIL'}] {acc.command}")
        lines += [f"## {i}. {'PASS' if passed else 'FAIL'}: `{acc.command}`",
                  *([f"expected in stdout: `{acc.expect}`"] if acc.expect else []),
                  "```text", (r.stdout + r.stderr).strip()[-4000:], "```", ""]
    evidence = project / "_receipts" / f"{tid}.acceptance.md"
    evidence.write_text("\n".join(lines) + "\n")
    if not ok:
        raise Abort(f"acceptance failed; evidence in {evidence.relative_to(project)}. "
                    "Write a follow-up ticket; do not fix it yourself.")
    changed = sorted(changed_files(project, t.header["base"]))
    work = [p for p in changed if p in t.allowed_files or p.startswith(f"_receipts/{tid}.")]
    head = commit(project, f"{tid}: {t.title}", work)
    t.header["head"], t.header["state"] = head, "review"
    t.save()
    commit(project, f"{tid}: accepted at {head}, ready for review", [str(t.path.relative_to(project))])
    say(f"accepted {tid}: head={head}. next: hydra-pod-dispatch review {tid}")


def review_prompt(project: Path, t: tk.Ticket, reviewer: str) -> str:
    earlier = t.header.get("earlier_specs") or []
    if reviewer == "opencode":
        text = template_block("reviewer.md")
        subs = {"<ticket>": t.id, "<base>..<head>": f"{t.header['base']}..{t.header['head']}",
                "<base>": t.header["base"], "<head>": t.header["head"], "<now>": now_iso(),
                "<test command>": t.header["test_command"],
                "<earlier specs>": " and ".join(earlier) if earlier else "none"}
        for k, v in subs.items():
            text = text.replace(k, v)
        return text
    raise Abort(f"unknown reviewer {reviewer!r}")


def review(project: Path, tid: str, reviewer: str) -> None:
    t = tk.find(project, tid)
    require_state(t, "review")
    base, head = t.header.get("base"), t.header.get("head")
    if not (base and head):
        raise Abort(f"{tid} has no base/head; run claim and accept first")
    if reviewer == "opencode":
        gate_opencode_label("Z.AI Coding Plan")
        prompt = review_prompt(project, t, reviewer)
        out = project / "_receipts" / f"{tid}.review.jsonl"
        say(f"reviewing {tid} ({base}..{head}) with opencode / zai-coding-plan/glm-5.3 ...")
        q_before = quota.zai_quota()
        with open(project / "_receipts" / f"{tid}.review.watchdog.log", "w") as lf:
            rc = subprocess.run([watchdog(project), str(out), "1200", "--", "opencode", "run",
                                 "--standalone", "--format", "json", "-m",
                                 "zai-coding-plan/glm-5.3", "--agent", "reviewer", prompt],
                                cwd=project, stdin=subprocess.DEVNULL, stderr=lf).returncode
        report = project / "_receipts" / f"{tid}.review.md"
        text = subprocess.run([str(REPO / "scripts/extract-report.py"), str(out)],
                              capture_output=True, text=True).stdout
        m = jsonl_metrics(out)
        credits = quota.used_between(q_before, quota.zai_quota())
        record_cost(project, tid, {"phase": "review", "provider": "opencode/zai-coding-plan",
                                   "model": "glm-5.3", "exit": rc, "zai_credits": credits, **m})
        say(f"reviewer exit {rc}; {m['seconds']}s, {m['tool_calls']} tool calls, {m['denied']} denied, "
            f"Z.ai credits {credits if credits is not None else 'n/a'}")
    elif reviewer == "zcode":
        gate_provider("zcode-lite")
        prep = subprocess.run([str(REPO / "scripts/zcode-review-prep.sh"), tid, base, head,
                               str(project)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if prep.returncode != 0:
            raise Abort("zcode-review-prep failed: " + prep.stderr.strip()[:300])
        report = project / "_receipts" / f"{tid}.review-zcode.md"
        say(f"reviewing {tid} ({base}..{head}) with ZCode ...")
        zc = registry.get("zcode-lite")
        prompt_text = (project / "_receipts" / f"{tid}.zcode-prompt.txt").read_text()
        q_before, started = quota.zai_quota(), dt.datetime.now()
        rc, text, detail = zc.run_review(prompt_text)
        credits = quota.used_between(q_before, quota.zai_quota())
        usage = getattr(zc, "last_usage", None) or {}
        record_cost(project, tid, {"phase": "review", "provider": "zcode-lite", "model": "GLM-5.3",
                                   "exit": rc, "zai_credits": credits,
                                   "seconds": round((dt.datetime.now() - started).total_seconds()),
                                   "tool_calls": None, "denied": None,
                                   "tokens": {"input": usage.get("inputTokens"),
                                              "output": usage.get("outputTokens"),
                                              "reasoning": usage.get("reasoningTokens"),
                                              "cache_read": usage.get("cacheReadTokens")},
                                   "list_cost_usd": None})
        say(f"reviewer exit {rc} ({detail}); Z.ai credits {credits if credits is not None else 'n/a'}")
    else:
        raise Abort(f"unknown reviewer {reviewer!r} (opencode | zcode)")
    complete = "Reviewer:" in text
    if not complete:
        raise Abort(f"review failed (exit {rc}, no complete report)")
    if rc != 0:
        # Seen live: the final answer arrives, then the provider connection drops
        # (ECONNRESET) and opencode exits 1. A complete report is still valid.
        say(f"warning: reviewer exited {rc} after producing a complete report; report kept")
    report.write_text(text.rstrip() + "\n")
    probes = sum(1 for l in text.splitlines() if "PROBE:" in l)
    say(f"report: {report.relative_to(project)} ({probes} PROBE lines). "
        f"next: hydra-pod-dispatch probes {tid} --run, then validate findings")


def probes(project: Path, tid: str, do_run: bool, report_name: str | None) -> int:
    t = tk.find(project, tid)
    head = t.header.get("head") or "HEAD"
    report = project / "_receipts" / (report_name or f"{tid}.review.md")
    args = [str(REPO / "scripts/probe-run.py"), str(report), "--project", str(project), "--ref", head]
    return subprocess.run(args + (["--run"] if do_run else []), stdin=subprocess.DEVNULL).returncode


def close(project: Path, tid: str) -> None:
    t = tk.find(project, tid)
    require_state(t, "review")
    dest = project / "_tickets" / "done" / t.path.name
    git(project, "mv", str(t.path.relative_to(project)), str(dest.relative_to(project)))
    t.path = dest
    t.header["state"] = "done"
    t.save()
    sha = commit(project, f"{tid}: close", [str(dest.relative_to(project))])
    say(f"closed {tid}: commit {sha}")


def load_costs(project: Path, tid: str) -> list[dict]:
    f = project / "_receipts" / f"{tid}.costs.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def cost_totals(entries: list[dict]) -> dict:
    tot = {"runs": len(entries), "seconds": 0, "tokens": 0, "zai_credits": 0, "list_cost_usd": 0.0}
    for e in entries:
        tot["seconds"] += e.get("seconds") or 0
        tok = e.get("tokens") or {}
        tot["tokens"] += sum(int(tok.get(k) or 0) for k in ("input", "output", "reasoning"))
        tot["zai_credits"] += e.get("zai_credits") or 0
        tot["list_cost_usd"] += e.get("list_cost_usd") or 0
    tot["list_cost_usd"] = round(tot["list_cost_usd"], 4)
    return tot


def costs(project: Path, tid: str | None) -> None:
    ids = [tid] if tid else [t.id for t in tk.all_tickets(project)]
    print("| ticket | phase | provider | seconds | tool calls | denied | tokens in/out | Z.ai credits | catalog $ |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    grand = []
    for i in ids:
        entries = load_costs(project, i)
        grand += entries
        for e in entries:
            tok = e.get("tokens") or {}
            print(f"| {i} | {e.get('phase')} | {e.get('provider')} | {e.get('seconds')} | "
                  f"{e.get('tool_calls')} | {e.get('denied')} | {tok.get('input')}/{tok.get('output')} | "
                  f"{e.get('zai_credits') if e.get('zai_credits') is not None else '-'} | "
                  f"{e.get('list_cost_usd') if e.get('list_cost_usd') is not None else '-'} |")
    t = cost_totals(grand)
    print(f"\ntotal: {t['runs']} runs, {t['seconds']}s, {t['tokens']} tokens, "
          f"{t['zai_credits']} Z.ai credits, ${t['list_cost_usd']} catalog estimate "
          "(OpenCode Go is a subscription: the catalog figure is informational, not billed)")


NEXT = {"open": "hydra-pod-dispatch claim {id}", "doing": "hydra-pod-dispatch build {id}, then accept {id}",
        "review": "hydra-pod-dispatch review {id}; validate; fix ticket or close {id}", "done": "-"}


def status(project: Path, write: bool = True) -> None:
    rows = ["| ticket | state | base | head | runs | tokens | Z.ai credits | next |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t in tk.all_tickets(project):
        c = cost_totals(load_costs(project, t.id))
        rows.append(f"| {t.id} | {t.state} | {t.header.get('base') or '-'} | "
                    f"{t.header.get('head') or '-'} | {c['runs'] or '-'} | {c['tokens'] or '-'} | "
                    f"{c['zai_credits'] or '-'} | {NEXT.get(t.state, '-').format(id=t.id)} |")
    table = "\n".join(rows)
    print(table)
    if write:
        (project / "_tickets" / "STATE.md").write_text(
            f"# Ticket state\n\n> generated by hydra-pod-dispatch status at {now_iso()}\n\n{table}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hydra-pod-dispatch", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=".", help="project root (default: current directory)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("claim"); c.add_argument("ticket"); c.add_argument("--skip-preflight", action="store_true")
    for name in ("build", "accept", "close", "preflight"):
        sub.add_parser(name).add_argument("ticket")
    k = sub.add_parser("costs"); k.add_argument("ticket", nargs="?")
    r = sub.add_parser("review"); r.add_argument("ticket"); r.add_argument("--reviewer", default="opencode", choices=["opencode", "zcode"])
    p = sub.add_parser("probes"); p.add_argument("ticket"); p.add_argument("--run", action="store_true"); p.add_argument("--report")
    s = sub.add_parser("status"); s.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    project = Path(a.project).resolve()
    try:
        if a.cmd == "claim":
            claim(project, a.ticket, skip_preflight=a.skip_preflight)
        elif a.cmd == "preflight":
            preflight(project, a.ticket)
        elif a.cmd == "costs":
            costs(project, a.ticket)
        elif a.cmd == "build":
            build(project, a.ticket)
        elif a.cmd == "accept":
            accept(project, a.ticket)
        elif a.cmd == "review":
            review(project, a.ticket, a.reviewer)
        elif a.cmd == "probes":
            return probes(project, a.ticket, a.run, a.report)
        elif a.cmd == "close":
            close(project, a.ticket)
        elif a.cmd == "status":
            status(project, write=not a.no_write)
        return 0
    except (Abort, FileNotFoundError, ValueError) as e:
        print(f"hydra-pod-dispatch: {e}", file=sys.stderr)
        return 1
