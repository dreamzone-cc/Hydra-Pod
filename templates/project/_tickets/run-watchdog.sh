#!/usr/bin/env bash
# Run an opencode headless command with a startup watchdog.
# usage: run-watchdog.sh <out.jsonl> <total-timeout-s> -- opencode run ... "<prompt>"
# If <out.jsonl> gets no event within STARTUP_SECS, kill and retry (max 3 attempts).
set -u
out=$1; total=$2; shift 3
STARTUP_SECS=${STARTUP_SECS:-90}
for attempt in 1 2 3; do
  : > "$out"
  # stdin must be closed: `opencode run` waits for stdin when it is not a terminal.
  timeout "$total" "$@" > "$out" 2>&1 < /dev/null &
  pid=$!
  waited=0
  while kill -0 "$pid" 2>/dev/null && [ ! -s "$out" ] && [ "$waited" -lt "$STARTUP_SECS" ]; do
    sleep 2; waited=$((waited+2))
  done
  if [ -s "$out" ] || ! kill -0 "$pid" 2>/dev/null; then
    wait "$pid"; rc=$?
    echo "attempt=$attempt exit=$rc" >&2
    exit "$rc"
  fi
  echo "attempt=$attempt: no event in ${STARTUP_SECS}s, retrying" >&2
  pkill -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
done
echo "gave up after 3 attempts" >&2
exit 125
