"""Cache of the last known status per provider. Holds no secrets."""

import json
import os

from . import paths
from .status import ProviderStatus


def load() -> dict[str, ProviderStatus]:
    try:
        raw = json.loads(paths.STATUS_CACHE.read_text())
        return {k: ProviderStatus.from_dict(v) for k, v in raw.items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def save(status: ProviderStatus) -> None:
    data = {k: v.to_dict() for k, v in load().items()}
    data[status.provider] = status.to_dict()
    paths.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = paths.STATUS_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, paths.STATUS_CACHE)
