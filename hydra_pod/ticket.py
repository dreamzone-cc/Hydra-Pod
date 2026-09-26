"""Structured ticket header (recommendation R2, docs/11).

A ticket file starts with a header between `---` lines:

    ---
    ticket: T4-example
    state: open                 # open | doing | review | done
    worker: opencode-go/deepseek-v4.1-flash
    base:                       # set by `hydra-pod-dispatch claim` (HEAD at claim)
    head:                       # set by `hydra-pod-dispatch accept` (the acceptance commit)
    test_command: python3 -B -m unittest discover -s tests -v
    allowed_files:
      - src/sandbox/textutil.py
      - tests/test_textutil.py
    acceptance:
      - python3 -B -m unittest discover -s tests -v
      - python3 -B -c "print(1)" ==> 1
    earlier_specs:
      - _tickets/done/T1-top-words.md
    reviewers:                  # opencode (default) and/or zcode
      - opencode
    ---

Values are plain text (no YAML quoting rules): `key: value` or `key:` followed
by `  - item` lines. An acceptance entry may end with ` ==> <text>`: the
command must exit 0 and its stdout must contain <text>.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

STATES = ("open", "doing", "review", "done")
LIST_KEYS = ("allowed_files", "acceptance", "earlier_specs", "reviewers")
SCALAR_KEYS = ("ticket", "state", "worker", "base", "head", "test_command")
FOLDER_OF = {"open": "open", "doing": "doing", "review": "doing", "done": "done"}


@dataclass
class Acceptance:
    command: str
    expect: str | None = None

    @classmethod
    def parse(cls, raw: str) -> "Acceptance":
        cmd, sep, expect = raw.partition(" ==> ")
        return cls(cmd.strip(), expect.strip() if sep else None)

    def render(self) -> str:
        return f"{self.command} ==> {self.expect}" if self.expect is not None else self.command


@dataclass
class Ticket:
    path: Path
    header: dict = field(default_factory=dict)
    body: str = ""

    # ---- accessors ------------------------------------------------------
    @property
    def id(self) -> str:
        return self.header.get("ticket") or self.path.stem

    @property
    def state(self) -> str:
        # Tickets written before the header existed: their folder is the state.
        folder = self.path.parent.name
        return self.header.get("state") or {"done": "done", "doing": "doing"}.get(folder, folder or "open")

    @property
    def allowed_files(self) -> list[str]:
        return list(self.header.get("allowed_files") or [])

    @property
    def acceptance(self) -> list[Acceptance]:
        return [Acceptance.parse(a) for a in self.header.get("acceptance") or []]

    @property
    def reviewers(self) -> list[str]:
        return list(self.header.get("reviewers") or ["opencode"])

    @property
    def title(self) -> str:
        m = re.search(r"^#\s+(.+)$", self.body, re.M)
        return m.group(1).strip() if m else self.id

    # ---- io -------------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "Ticket":
        text = Path(path).read_text(encoding="utf-8")
        header, body = parse_header(text)
        return cls(Path(path), header, body)

    def save(self, path: Path | None = None) -> None:
        target = Path(path or self.path)
        target.write_text(render_header(self.header) + self.body, encoding="utf-8")
        self.path = target

    def validate(self) -> list[str]:
        problems = []
        if self.state not in STATES:
            problems.append(f"state {self.state!r} not in {STATES}")
        if not self.allowed_files:
            problems.append("allowed_files is empty")
        if not self.acceptance:
            problems.append("acceptance is empty")
        if not self.header.get("test_command"):
            problems.append("test_command is missing")
        return problems


def parse_header(text: str) -> tuple[dict, str]:
    """Split a ticket into (header dict, body). No header -> ({}, text)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("ticket header is not closed with ---")
    lines = text[4:end].splitlines()
    body = text[end + 5:]
    header: dict = {}
    key = None
    for raw in lines:
        line = re.sub(r"\s+#.*$", "", raw) if not raw.lstrip().startswith("- ") else raw
        if not line.strip():
            continue
        m_item = re.match(r"^\s+-\s?(.*)$", line)
        if m_item and key in LIST_KEYS:
            header.setdefault(key, []).append(m_item.group(1).rstrip())
            continue
        m_kv = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if not m_kv:
            raise ValueError(f"bad header line: {raw!r}")
        key, value = m_kv.group(1), m_kv.group(2).strip()
        if key in LIST_KEYS:
            header[key] = [value] if value else []
        else:
            header[key] = value
    return header, body


def render_header(header: dict) -> str:
    out = ["---"]
    ordered = [k for k in SCALAR_KEYS if k in header] + \
              [k for k in LIST_KEYS if k in header] + \
              [k for k in header if k not in SCALAR_KEYS + LIST_KEYS]
    for k in ordered:
        v = header[k]
        if isinstance(v, list):
            out.append(f"{k}:")
            out += [f"  - {item}" for item in v]
        else:
            out.append(f"{k}: {v}".rstrip())
    out.append("---")
    return "\n".join(out) + "\n"


def find(project: Path, ticket_id: str) -> Ticket:
    """Locate a ticket by id (file stem) under _tickets/{open,doing,done}."""
    for folder in ("doing", "open", "done", "blocked", "dropped"):
        p = project / "_tickets" / folder / f"{ticket_id}.md"
        if p.is_file():
            return Ticket.load(p)
    raise FileNotFoundError(f"ticket {ticket_id} not found under {project}/_tickets/")


def all_tickets(project: Path) -> list[Ticket]:
    out = []
    for folder in ("open", "doing", "done", "blocked", "dropped"):
        for p in sorted((project / "_tickets" / folder).glob("*.md")):
            try:
                out.append(Ticket.load(p))
            except ValueError:
                out.append(Ticket(p, {"state": "?"}, ""))
    return out
