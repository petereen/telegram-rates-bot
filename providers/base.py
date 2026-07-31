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
import threading
from abc import ABC, abstractmethod
from typing import Any

from db.supabase_client import (
    get_cached_rate,
    get_daily_cached_rate,
    set_cached_rate,
)

log = logging.getLogger(__name__)

_daily_locks: dict[tuple[str, str], threading.Lock] = {}
_daily_locks_guard = threading.Lock()


def _daily_lock(provider: str, symbol: str) -> threading.Lock:
    """Return one process-wide refresh lock for a provider/pair."""
    key = (provider, symbol)
    with _daily_locks_guard:
        return _daily_locks.setdefault(key, threading.Lock())


class BaseProvider(ABC):
    NAME: str = ""
    DISPLAY_NAME: str = ""
    VISIBLE: bool = True
    # Daily-published sources keep one durable snapshot per Ulaanbaatar day.
    # Live market/crypto providers retain the shorter global CACHE_TTL.
    CACHE_DAILY: bool = False
    CACHE_UTC_OFFSET_HOURS: int = 8
    PAIRS: dict[str, str] = {}
    FORMULA_FIELDS: dict[str, tuple[str, ...]] = {}

    def formula_fields(self, symbol: str) -> tuple[str, ...]:
        """Return numeric payload fields that formulas may reference."""
        return self.FORMULA_FIELDS.get(symbol, ())

    def supports_pair(self, symbol: str) -> bool:
        """Return whether this provider can fetch a currency pair."""
        return symbol in self.PAIRS

    # ── public entry point (cache-aware) ───────────────────────────────

    def get_rate(self, symbol: str) -> dict[str, Any]:
        """Return rate_data dict, using cache when available."""
        if self.CACHE_DAILY:
            return self._get_daily_rate(symbol)

        try:
            cached = get_cached_rate(self.NAME, symbol)
            if cached is not None:
                log.debug("Cache hit  %s/%s", self.NAME, symbol)
                return cached
        except Exception as exc:
            log.warning("Cache read error %s/%s: %s", self.NAME, symbol, exc)

        log.info("Fetching   %s/%s", self.NAME, symbol)
        data = self.fetch(symbol)

        try:
            set_cached_rate(self.NAME, symbol, data)
        except Exception as exc:
            log.warning("Cache write error %s/%s: %s", self.NAME, symbol, exc)

        return data

    def _get_daily_rate(self, symbol: str) -> dict[str, Any]:
        """Return today's durable snapshot, fetching it only when absent."""
        try:
            cached = get_daily_cached_rate(
                self.NAME,
                symbol,
                utc_offset_hours=self.CACHE_UTC_OFFSET_HOURS,
            )
            if cached is not None:
                log.debug("Daily cache hit  %s/%s", self.NAME, symbol)
                return cached
        except Exception as exc:
            log.warning("Daily cache read error %s/%s: %s", self.NAME, symbol, exc)

        # /api/rates and /api/calculated load concurrently and may depend on
        # the same pair. Recheck after locking so only one upstream call wins.
        with _daily_lock(self.NAME, symbol):
            try:
                cached = get_daily_cached_rate(
                    self.NAME,
                    symbol,
                    utc_offset_hours=self.CACHE_UTC_OFFSET_HOURS,
                )
                if cached is not None:
                    return cached
            except Exception as exc:
                log.warning(
                    "Daily cache recheck error %s/%s: %s",
                    self.NAME,
                    symbol,
                    exc,
                )

            log.info("Daily fetch   %s/%s", self.NAME, symbol)
            data = self.fetch(symbol)
            # A temporary upstream error must not become the result for the
            # rest of the day. Successful provider payloads expose at least
            # one of the numeric fields declared for formulas.
            fields = self.formula_fields(symbol)
            cacheable = any(data.get(field) is not None for field in fields)
            if cacheable:
                try:
                    set_cached_rate(self.NAME, symbol, data)
                except Exception as exc:
                    log.warning(
                        "Daily cache write error %s/%s: %s",
                        self.NAME,
                        symbol,
                        exc,
                    )
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
    return {
        name: cls()
        for name, cls in _registry.items()
        if getattr(cls, "VISIBLE", True)
    }
