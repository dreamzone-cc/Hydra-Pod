"""Connection states shared by every provider.

A provider never stores credentials itself; it reports what the official tool
behind it says. `classify_failure` maps an official tool's error text to a
state so every provider uses the same vocabulary.
"""

import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum


class State(str, Enum):
    NOT_CONNECTED = "Not Connected"
    AUTHENTICATING = "Authenticating"
    CONNECTED = "Connected"
    AUTH_FAILED = "Authentication Failed"
    EXPIRED = "Expired / Re-authentication Required"


@dataclass
class ProviderStatus:
    provider: str
    state: State
    detail: str = ""
    model: str | None = None
    checked_at: float = field(default_factory=time.time)
    # True when the state comes from a live check (a test call), False when it
    # is inferred without spending quota.
    verified: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProviderStatus":
        d = dict(d)
        d["state"] = State(d["state"])
        return cls(**d)


# Order matters: the first matching rule wins.
_FAILURE_RULES = [
    (re.compile(r"\b(1308|1310)\b|rate_limit|limit exhausted|quota", re.I),
     State.CONNECTED, "quota exhausted"),
    (re.compile(r"\b401\b|unauthori[sz]ed|token (has )?expired|invalid[_ ]token|re-?login", re.I),
     State.EXPIRED, "session expired or revoked; run connect again"),
    (re.compile(r"authorization timed out", re.I),
     State.AUTH_FAILED, "authorization timed out: approve in the browser within ~5 minutes"),
    (re.compile(r"authorization failed|access[_ ]denied", re.I),
     State.AUTH_FAILED, "authorization was rejected"),
    (re.compile(r"model creation failed|not logged in|no credentials|no auth", re.I),
     State.NOT_CONNECTED, "no active login"),
]


def classify_failure(text: str) -> tuple[State, str]:
    """Map an official tool's failure output to (state, human detail)."""
    for pattern, state, detail in _FAILURE_RULES:
        if pattern.search(text or ""):
            return state, detail
    first = (text or "").strip().splitlines()[:1]
    return State.AUTH_FAILED, first[0][:200] if first else "unknown failure"
