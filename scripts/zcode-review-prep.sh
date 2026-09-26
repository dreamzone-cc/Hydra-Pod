#!/usr/bin/env bash
# Prepare a read-only ZCode review for one ticket (the ZCode reviewer cannot run git).
# usage: zcode-review-prep.sh <ticket> <base> <head> [project-dir]
# Writes into <project>/_receipts/:
#   <ticket>.diff      git diff <base>..<head> -- src tests (all files if src/tests are absent)
#   <ticket>.commits   git log --format='%h %s' <base>..<head>
#   <ticket>.zcode-prompt.txt   prompts/reviewer-zcode.md filled with absolute paths
# If the working tree differs from <head>, a snapshot of <head> is extracted to
# <cache>/hydra-pod/snapshots/<ticket>/ (legacy <cache>/opus-manager) and the
# prompt points there.
# Then run: hydra-pod-connect review zcode-lite --prompt-file <prompt> --out _receipts/<ticket>.review.md
set -euo pipefail
ticket=$1 base=$2 head=$3
proj=$(cd "${4:-.}" && pwd)
here=$(cd "$(dirname "$0")/.." && pwd)
cache=${XDG_CACHE_HOME:-$HOME/.cache}
if [ ! -e "$cache/hydra-pod" ] && [ -e "$cache/opus-manager" ]; then
  cache=$cache/opus-manager                # legacy fallback
else
  cache=$cache/hydra-pod
fi
cd "$proj"
git rev-parse --verify -q "$base^{commit}" >/dev/null || { echo "unknown base $base" >&2; exit 2; }
git rev-parse --verify -q "$head^{commit}" >/dev/null || { echo "unknown head $head" >&2; exit 2; }
mkdir -p _receipts
paths=()
for d in src tests; do [ -e "$d" ] && paths+=("$d"); done
git diff "$base..$head" -- "${paths[@]}" > "_receipts/$ticket.diff"
git log --format='%h %s' "$base..$head" > "_receipts/$ticket.commits"

root=$proj
if ! git diff --quiet "$head" -- "${paths[@]}"; then
  snap=$cache/snapshots/$ticket
  rm -rf "$snap"; mkdir -p "$snap"
  git archive "$head" | tar -x -C "$snap"
  # the review inputs live in the real project; copy them next to the snapshot
  mkdir -p "$snap/_receipts" "$snap/_tickets"
  cp "_receipts/$ticket".* "$snap/_receipts/" 2>/dev/null || true
  cp -R _tickets/. "$snap/_tickets/" 2>/dev/null || true
  root=$snap
  echo "working tree differs from $head: reviewing snapshot $snap" >&2
fi

ticket_file=$(ls "$root"/_tickets/*/"$ticket".md 2>/dev/null | head -1)
[ -n "$ticket_file" ] || { echo "ticket $ticket.md not found under _tickets/" >&2; exit 2; }
now=$(date -Iseconds)
earlier=$(ls "$root"/_tickets/done/*.md 2>/dev/null | grep -v "/$ticket.md$" | paste -sd ' ' -)
prompt=$(python3 - "$here/prompts/reviewer-zcode.md" "$root" "$ticket" "$ticket_file" "$now" "${earlier:-none}" <<'PY'
import re, sys
doc, root, ticket, ticket_file, now, earlier = sys.argv[1:]
text = re.search(r"^```text\n(.*?)^```", open(doc, encoding="utf-8").read(), re.S | re.M).group(1)
text = text.replace("<ABS_PROJECT>/_tickets/doing/<ticket>.md", ticket_file)
text = text.replace("<ABS_PROJECT>", root).replace("<ticket>", ticket)
text = text.replace("<NOW>", now).replace("<EARLIER_SPECS>", earlier)
sys.stdout.write(text)
PY
)
printf '%s\n' "$prompt" > "_receipts/$ticket.zcode-prompt.txt"
echo "_receipts/$ticket.zcode-prompt.txt"
