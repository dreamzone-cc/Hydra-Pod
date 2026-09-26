"""Provider registry: providers.json entries mapped to implementation classes.

Adding a provider = one entry in providers.json + (for a new `kind`) one class
registered in KINDS. Kinds whose implementation is not written yet load as
`Unimplemented`, so `status` can still list them.
"""

import importlib
import json
from pathlib import Path

from ..status import ProviderStatus, State
from .base import Provider

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDERS_FILE = REPO_ROOT / "providers.json"

# kind -> "module:Class" (relative to hydra_pod.providers)
KINDS = {
    "zcode-cli": "zcode_lite:ZCodeLite",
    "opencode": "opencode_go:OpenCodeProvider",
}


class Unimplemented(Provider):
    def _todo(self) -> ProviderStatus:
        return ProviderStatus(self.id, State.NOT_CONNECTED,
                              detail=f"kind {self.spec.get('kind')!r} not implemented yet")

    def status(self):
        return self._todo()

    def test(self):
        return self._todo()

    def connect(self, *, open_browser=True, method=None):
        return self._todo()

    def disconnect(self):
        return self._todo()


def load_specs(path: Path = PROVIDERS_FILE) -> dict[str, dict]:
    return json.loads(path.read_text())


def _class_for(kind: str):
    target = KINDS.get(kind)
    if not target:
        return Unimplemented
    module, cls = target.split(":")
    try:
        mod = importlib.import_module(f"{__package__}.{module}")
    except ModuleNotFoundError as e:
        if e.name and e.name.endswith(module):
            return Unimplemented
        raise
    return getattr(mod, cls)


def get(provider_id: str, specs: dict | None = None) -> Provider:
    specs = specs if specs is not None else load_specs()
    if provider_id not in specs:
        raise KeyError(f"unknown provider {provider_id!r}; known: {', '.join(specs)}")
    spec = specs[provider_id]
    return _class_for(spec.get("kind", ""))(provider_id, spec)


def all_providers(specs: dict | None = None) -> list[Provider]:
    specs = specs if specs is not None else load_specs()
    return [get(pid, specs) for pid in specs]
