#!/usr/bin/env bash
# Show Z.ai Coding Plan quota (read-only; does not consume quota).
# Key file: $ZAI_KEY_FILE, else <config>/hydra-pod/zai.key (mode 600), where
# <config> falls back to the legacy <config>/opus-manager when only that exists.
# The key is sent only as the Authorization header and never printed.
set -euo pipefail
config=${XDG_CONFIG_HOME:-$HOME/.config}
if [ ! -e "$config/hydra-pod" ] && [ -e "$config/opus-manager" ]; then
  brand=$config/opus-manager               # legacy fallback
else
  brand=$config/hydra-pod
fi
key_file=${ZAI_KEY_FILE:-$brand/zai.key}
if [ ! -r "$key_file" ]; then
  echo "key file not readable: $key_file" >&2
  exit 1
fi
perm=$(stat -c %a "$key_file")
[ "$perm" = 600 ] || echo "warning: $key_file has mode $perm (expected 600)" >&2

body=$(curl -sS -m 20 https://api.z.ai/api/monitor/usage/quota/limit \
  -H "Authorization: $(tr -d '[:space:]' < "$key_file")" \
  -H "Accept-Language: en-US,en")

BODY=$body python3 - <<'EOF'
import datetime, json, os, sys

body = json.loads(os.environ["BODY"])
if not body.get("success"):
    sys.exit("quota query failed: %s %s" % (body.get("code"), body.get("msg")))
data = body["data"]
units = {3: "h", 6: "w"}  # observed codes: 3 = hours, 6 = weeks
print("plan level:", data.get("level"))
for lim in data.get("limits", []):
    window = "%s%s" % (lim.get("number"), units.get(lim.get("unit"), "?"))
    line = "  %4s: %6s / %s used, %s left" % (
        window, lim.get("currentValue", 0), lim.get("usage"), lim.get("remaining"))
    reset = lim.get("nextResetTime")
    if reset:
        line += "  (resets %s)" % datetime.datetime.fromtimestamp(reset / 1000).strftime("%a %d %b %H:%M")
    print(line)
EOF
