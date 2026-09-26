"""Run official tools as subprocesses. Output is returned, never logged here."""

import subprocess
from dataclasses import dataclass


@dataclass
class Result:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def run(argv: list[str], *, env: dict | None = None, cwd: str | None = None,
        timeout: float = 120, stdin_devnull: bool = True) -> Result:
    try:
        p = subprocess.run(argv, env=env, cwd=cwd, timeout=timeout, text=True,
                           capture_output=True,
                           stdin=subprocess.DEVNULL if stdin_devnull else None)
        return Result(p.returncode, p.stdout, p.stderr)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return Result(124, out, err, timed_out=True)
    except FileNotFoundError as e:
        return Result(127, "", str(e))


def run_attached(argv: list[str], *, env: dict | None = None, cwd: str | None = None,
                 timeout: float | None = None) -> int:
    """Run with the user's terminal attached (for interactive official flows)."""
    try:
        return subprocess.run(argv, env=env, cwd=cwd, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        return 124
    except FileNotFoundError:
        return 127
