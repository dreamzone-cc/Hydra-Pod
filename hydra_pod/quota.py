"""Z.ai GLM Coding Plan quota (read-only; does not consume quota).

Same official endpoint as scripts/zai-quota.sh. The key is read from
paths.CONFIG_DIR/zai.key (default ~/.config/hydra-pod/zai.key, legacy
~/.config/opus-manager/zai.key) or $ZAI_KEY_FILE, and only ever sent as the
Authorization header; it is never returned, printed or logged.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from . import paths

URL = "https://api.z.ai/api/monitor/usage/quota/limit"
UNITS = {3: "h", 6: "w"}      # observed unit codes: 3 = hours, 6 = weeks


def key_file() -> Path:
    return Path(os.environ.get("ZAI_KEY_FILE") or paths.CONFIG_DIR / "zai.key")


def zai_quota(timeout: float = 15) -> dict | None:
    """{"level": str, "windows": [{"window", "used", "total", "remaining", "resets_at"}]} or None."""
    try:
        key = key_file().read_text().strip()
    except OSError:
        return None
    if not key:
        return None
    req = urllib.request.Request(URL, headers={"Authorization": key, "Accept-Language": "en-US,en"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not body.get("success"):
        return None
    data = body.get("data") or {}
    windows = []
    for lim in data.get("limits") or []:
        windows.append({
            "window": f"{lim.get('number')}{UNITS.get(lim.get('unit'), '?')}",
            "used": int(lim.get("currentValue") or 0),
            "total": int(lim.get("usage") or 0),
            "remaining": int(lim.get("remaining") or 0),
            "resets_at": (lim.get("nextResetTime") or 0) / 1000 or None,
        })
    return {"level": data.get("level"), "windows": windows}


def used_between(before: dict | None, after: dict | None) -> int | None:
    """Credits consumed between two snapshots, from the shortest window (the 5h one)."""
    if not before or not after or not before["windows"] or not after["windows"]:
        return None
    b, a = before["windows"][0], after["windows"][0]
    if a["used"] < b["used"]:          # the window reset in between
        return None
    return a["used"] - b["used"]


def min_remaining(q: dict | None) -> int | None:
    if not q or not q["windows"]:
        return None
    return min(w["remaining"] for w in q["windows"])
