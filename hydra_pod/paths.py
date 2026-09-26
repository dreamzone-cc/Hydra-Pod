"""Filesystem locations owned by Hydra-Pod (XDG-style, outside any repo)."""

import os
from pathlib import Path


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


def brand_dir(base: Path) -> Path:
    """<base>/hydra-pod, or <base>/opus-manager when only the legacy dir exists."""
    new = base / "hydra-pod"
    legacy = base / "opus-manager"  # legacy name: an install from before Hydra-Pod
    return legacy if not new.exists() and legacy.exists() else new


DATA_DIR = brand_dir(_xdg("XDG_DATA_HOME", ".local/share"))
CACHE_DIR = brand_dir(_xdg("XDG_CACHE_HOME", ".cache"))
CONFIG_DIR = brand_dir(_xdg("XDG_CONFIG_HOME", ".config"))

# Extracted official ZCode runtimes, one folder per ZCode app version.
ZCODE_RUNTIME_ROOT = DATA_DIR / "zcode"
# Isolated ZCode data dir (ZCODE_DATA_BASE_DIR): the official CLI keeps its own
# session here, separate from the ZCode desktop app. We never read its files.
ZCODE_HOME = DATA_DIR / "zcode-home"
STATUS_CACHE = CACHE_DIR / "status.json"
