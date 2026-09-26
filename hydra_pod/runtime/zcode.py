"""Locate, extract and describe the official ZCode CLI runtime.

Source of truth is the ZCode desktop app the user installed (no downloads):
the AppImage registered in ~/.local/share/applications/zcode.desktop, falling
back to the newest ~/ZCode/ZCode-*.AppImage. From it we extract only
`resources/glm/` (the agent CLI, `zcode.cjs`) plus the bundled
`zcode-builtin.json`, which the CLI expects at `glm/provider/`.

Nothing here reads ZCode credentials. The CLI runs with
ZCODE_DATA_BASE_DIR=paths.ZCODE_HOME so its login is isolated from the
desktop app. HOME is left untouched: the official login opens the default
browser through xdg-open, which needs the real HOME.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import paths
from .proc import run

APPIMAGE_RE = re.compile(r"ZCode-(\d+(?:\.\d+)+)-linux-x64\.AppImage$")
DESKTOP_ENTRY = Path.home() / ".local/share/applications/zcode.desktop"


@dataclass
class Runtime:
    app_version: str
    cli_version: str
    appimage: str
    root: str            # .../zcode/<app_version>
    entry: str           # .../glm/zcode.cjs
    entry_sha256: str

    @property
    def manifest_path(self) -> Path:
        return Path(self.root) / "manifest.json"


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def find_appimage() -> Path | None:
    """The installed ZCode AppImage: the registered one, else the newest in ~/ZCode."""
    try:
        for line in DESKTOP_ENTRY.read_text().splitlines():
            if line.startswith("Exec="):
                exe = line[5:].strip().split()[0].strip('"')
                if APPIMAGE_RE.search(exe) and Path(exe).is_file():
                    return Path(exe)
    except OSError:
        pass
    found = [p for p in (Path.home() / "ZCode").glob("ZCode-*-linux-x64.AppImage")
             if APPIMAGE_RE.search(p.name)]
    return max(found, key=lambda p: _version_key(APPIMAGE_RE.search(p.name).group(1)),
               default=None)


def app_version_of(appimage: Path) -> str:
    m = APPIMAGE_RE.search(appimage.name)
    if not m:
        raise ValueError(f"not a ZCode AppImage name: {appimage.name}")
    return m.group(1)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cli_version(entry: Path) -> str:
    r = run(["node", str(entry), "--version"], timeout=30)
    if r.code != 0:
        raise RuntimeError(f"zcode --version failed: {(r.stderr or r.stdout).strip()[:200]}")
    return r.stdout.strip().splitlines()[-1]


def installed() -> Runtime | None:
    """The newest extracted runtime with a readable manifest."""
    manifests = sorted(paths.ZCODE_RUNTIME_ROOT.glob("*/manifest.json"),
                       key=lambda p: _version_key(p.parent.name), reverse=True)
    for m in manifests:
        try:
            rt = Runtime(**json.loads(m.read_text()))
        except (OSError, ValueError, TypeError):
            continue
        if Path(rt.entry).is_file():
            return rt
    return None


def install(appimage: Path | None = None, force: bool = False) -> Runtime:
    """Extract glm/ and the builtin provider config from the installed app."""
    appimage = appimage or find_appimage()
    if appimage is None:
        raise FileNotFoundError("no installed ZCode AppImage found (~/ZCode/ZCode-*-linux-x64.AppImage)")
    version = app_version_of(appimage)
    root = paths.ZCODE_RUNTIME_ROOT / version
    if (root / "manifest.json").is_file() and not force:
        rt = installed()
        if rt and rt.app_version == version:
            return rt

    paths.ZCODE_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=paths.ZCODE_RUNTIME_ROOT, prefix=".extract-") as tmp:
        # --appimage-extract always writes ./squashfs-root in the cwd.
        r = run([str(appimage), "--appimage-extract", "resources/glm/*"], cwd=tmp, timeout=300)
        r2 = run([str(appimage), "--appimage-extract", "resources/config/provider/zcode-builtin.json"],
                 cwd=tmp, timeout=120)
        src = Path(tmp) / "squashfs-root" / "resources"
        glm, builtin = src / "glm", src / "config/provider/zcode-builtin.json"
        if not (glm / "zcode.cjs").is_file() or not builtin.is_file():
            raise RuntimeError("extraction incomplete: "
                               + (r.stderr or r2.stderr or "zcode.cjs or zcode-builtin.json missing")[:200])
        (glm / "provider").mkdir(exist_ok=True)
        shutil.copy2(builtin, glm / "provider" / "zcode-builtin.json")
        staged = Path(tmp) / "runtime"
        staged.mkdir()
        shutil.move(str(glm), staged / "glm")
        entry = staged / "glm" / "zcode.cjs"
        cli = cli_version(entry)
        if root.exists():
            shutil.rmtree(root)
        shutil.move(str(staged), root)

    entry = root / "glm" / "zcode.cjs"
    rt = Runtime(app_version=version, cli_version=cli, appimage=str(appimage),
                 root=str(root), entry=str(entry), entry_sha256=_sha256(entry))
    rt.manifest_path.write_text(json.dumps(asdict(rt), indent=2) + "\n")
    return rt


def env(base: dict | None = None) -> dict:
    """Environment for running the official CLI against the isolated ZCode home."""
    e = dict(os.environ if base is None else base)
    paths.ZCODE_HOME.mkdir(parents=True, exist_ok=True)
    os.chmod(paths.ZCODE_HOME, 0o700)
    e["ZCODE_DATA_BASE_DIR"] = str(paths.ZCODE_HOME)
    return e


def command(rt: Runtime, *args: str) -> list[str]:
    return ["node", rt.entry, *args]
