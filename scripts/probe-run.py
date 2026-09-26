#!/usr/bin/env python3
"""Run the `PROBE:` lines of a review report (recommendation R1, docs/11).

usage: probe-run.py <review.md> [--project DIR] [--ref REV] [--run]

A reviewer cannot execute code; instead it writes, under a finding,
    PROBE: <single Python expression> => <expected Python literal>
Without --run the probes are only listed (and checked against the safety
rules). With --run each allowed probe is evaluated in a throw-away copy of
the project at REV (git archive; default HEAD), with src/ on sys.path and a
10 s timeout, and the result is compared with the expected literal.

Probes are model-written code, so they are screened first: only calls to
__import__ of the project's own src packages or a few pure stdlib modules
are allowed, and open/exec/eval/compile/getattr-style builtins and dunder
attributes are refused.
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE_RE = re.compile(r"^\s*[-*]?\s*`?PROBE:\s*(?P<expr>.+?)\s*=>\s*(?P<expected>.+?)`?\s*$")
SAFE_STDLIB = {"collections", "math", "itertools", "functools", "re", "string", "json",
               "decimal", "fractions", "statistics", "unicodedata", "operator"}
BANNED_NAMES = {"open", "exec", "eval", "compile", "getattr", "setattr", "delattr", "globals",
                "locals", "vars", "input", "breakpoint", "exit", "quit", "help", "memoryview"}


def parse(report: str) -> list[tuple[str, str]]:
    probes = []
    for line in report.splitlines():
        m = PROBE_RE.match(line)
        if m:
            probes.append((m.group("expr").strip().strip("`"), m.group("expected").strip().strip("`")))
    return probes


def screen(expr: str, expected: str, src_packages: set[str]) -> str | None:
    """Return a refusal reason, or None if the probe may run."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return f"not a single expression ({e.msg})"
    try:
        ast.literal_eval(expected)
    except (ValueError, SyntaxError):
        return "expected value is not a Python literal"
    allowed_modules = src_packages | SAFE_STDLIB
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            return f"uses {node.id}()"
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return f"uses dunder attribute {node.attr}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
            arg = node.args[0] if node.args else None
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                return "__import__ needs a literal module name"
            if arg.value.split(".")[0] not in allowed_modules:
                return f"imports {arg.value} (allowed: project packages and pure stdlib)"
        if isinstance(node, (ast.Lambda, ast.NamedExpr)):
            return "lambdas and assignments are not allowed"
    return None


RUNNER = r"""
import ast, sys
sys.path.insert(0, "src")
expr, expected = sys.argv[1], sys.argv[2]
try:
    got = eval(compile(expr, "<probe>", "eval"), {"__builtins__": __builtins__})
except Exception as e:
    print(repr(f"{type(e).__name__}: {e}")); sys.exit(2)
print(repr(got))
sys.exit(0 if got == ast.literal_eval(expected) else 1)
"""


def run_probe(root: Path, expr: str, expected: str) -> tuple[str, str]:
    env = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(root)}
    try:
        p = subprocess.run([sys.executable, "-B", "-I", "-c", RUNNER, expr, expected], cwd=root,
                           env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=10)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", ""
    got = p.stdout.strip() or (p.stderr.strip().splitlines() or [""])[-1]
    return {0: "PASS", 1: "FAIL"}.get(p.returncode, "ERROR"), got


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("--project", default=".")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    probes = parse(Path(a.report).read_text(encoding="utf-8"))
    if not probes:
        print("no PROBE lines in the report")
        return 0
    src = project / "src"
    src_packages = {p.name for p in src.iterdir() if p.is_dir()} if src.is_dir() else set()

    rows, allowed = [], []
    for i, (expr, expected) in enumerate(probes, 1):
        why = screen(expr, expected, src_packages)
        rows.append([i, expr, expected, "REFUSED" if why else ("listed" if not a.run else ""),
                     why or ""])
        if not why:
            allowed.append(i)

    if a.run and allowed:
        with tempfile.TemporaryDirectory(prefix="probe-") as tmp:
            archive = subprocess.run(["git", "-C", str(project), "archive", a.ref],
                                     capture_output=True, check=True).stdout
            subprocess.run(["tar", "-x", "-C", tmp], input=archive, check=True)
            for row in rows:
                if row[0] in allowed:
                    row[3], row[4] = run_probe(Path(tmp), row[1], row[2])

    print(f"probes from {a.report} at {a.ref}:\n")
    print("| # | expression | expected | result | actual / reason |")
    print("| --- | --- | --- | --- | --- |")
    for i, expr, expected, result, detail in rows:
        cell = lambda s: str(s).replace("|", "\\|")
        print(f"| {i} | `{cell(expr)}` | `{cell(expected)}` | {result} | {cell(detail)} |")
    failed = sum(1 for r in rows if r[3] in ("FAIL", "ERROR", "TIMEOUT"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
