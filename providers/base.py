"""
providers.base – abstract base class and the Provider Factory.

Every concrete provider must:
  1. Subclass ``BaseProvider``.
  2. Set ``NAME`` (short label used in DB and UI, e.g. "CBR").
  3. Set ``PAIRS`` – a dict mapping symbol strings to human-readable labels
     that the provider can return.
  4. Implement ``fetch(symbol) -> dict`` returning at minimum
     ``{"lines": ["formatted line", ...]}`` ready for display.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from db.supabase_client import get_cached_rate, set_cached_rate

log = logging.getLogger(__name__)


class BaseProvider(ABC):
    NAME: str = ""
    PAIRS: dict[str, str] = {}

    # ── public entry point (cache-aware) ───────────────────────────────

    def get_rate(self, symbol: str) -> dict[str, Any]:
        """Return rate_data dict, using cache when available."""
        cached = get_cached_rate(self.NAME, symbol)
        if cached is not None:
            log.debug("Cache hit  %s/%s", self.NAME, symbol)
            return cached
        log.info("Fetching   %s/%s", self.NAME, symbol)
        data = self.fetch(symbol)
        set_cached_rate(self.NAME, symbol, data)
        return data

    @abstractmethod
    def fetch(self, symbol: str) -> dict[str, Any]:
        """Fetch live data from the external source (no cache)."""
        ...

    def format(self, symbol: str, data: dict[str, Any]) -> str:
        """Return display-ready string for a single symbol."""
        return "\n".join(data.get("lines", []))


# ── Factory ────────────────────────────────────────────────────────────

_registry: dict[str, type[BaseProvider]] = {}


def register_provider(cls: type[BaseProvider]) -> type[BaseProvider]:
    """Class decorator that auto-registers a provider by its NAME."""
    _registry[cls.NAME] = cls
    return cls


def get_provider(name: str) -> BaseProvider:
    """Instantiate and return a provider by NAME."""
    cls = _registry.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider: {name}")
    return cls()


def all_providers() -> dict[str, BaseProvider]:
    """Return {name: instance} for every registered provider."""
    return {name: cls() for name, cls in _registry.items()}
