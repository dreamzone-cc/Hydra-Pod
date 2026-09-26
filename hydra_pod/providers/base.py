"""Provider interface.

Layer boundaries:
- Authentication: `connect()` / `disconnect()` delegate to the provider's
  official login (browser OAuth or key prompt). No provider implements its
  own OAuth flow.
- Provider integration: `test()` performs a minimal live call through the
  official tool; `worker_command()` builds the headless command for a role.
- Credential storage: none here. The official tool keeps its own session or
  key; Hydra-Pod only caches non-secret status (see state_store).
"""

from abc import ABC, abstractmethod

from ..status import ProviderStatus


class Provider(ABC):
    def __init__(self, provider_id: str, spec: dict):
        self.id = provider_id
        self.spec = spec

    @property
    def display_name(self) -> str:
        return self.spec.get("display_name", self.id)

    @abstractmethod
    def status(self) -> ProviderStatus:
        """Best effort state without spending quota (no model call)."""

    @abstractmethod
    def test(self) -> ProviderStatus:
        """Live check: one minimal model call through the official tool."""

    @abstractmethod
    def connect(self, *, open_browser: bool = True, method: str | None = None) -> ProviderStatus:
        """Run the official login (method: provider-specific, e.g. "device" or "key"), then test()."""

    @abstractmethod
    def disconnect(self) -> ProviderStatus:
        """Run the official logout. Callers must confirm with the user first."""

    def disconnect_warning(self) -> str | None:
        """Text to show before disconnect, or None if disconnect is harmless."""
        return None

    def worker_command(self, role: str, prompt: str, cwd: str) -> list[str]:
        raise NotImplementedError(f"{self.id}: no worker command for role {role!r}")
