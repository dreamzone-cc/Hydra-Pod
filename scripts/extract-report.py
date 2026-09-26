#!/usr/bin/env python3
"""Print the final text answer from an `opencode run --format json` event log.

usage: extract-report.py <run.jsonl>

The reviewer's report (and a worker's closing summary) is the last event of
type "text". Non-JSON lines (e.g. stderr mixed into the file) are skipped.
Exits 1 if the log holds no text event, which usually means the run never
started; check the matching .watchdog.log.
"""

import json
import sys


def last_text(path: str) -> str | None:
    text = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "text":
                text = (event.get("part") or {}).get("text", text)
    return text


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    text = last_text(sys.argv[1])
    if not text:
        print(f"no text event in {sys.argv[1]}", file=sys.stderr)
        return 1
    print(text.rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
