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
from datetime import datetime, timedelta, timezone
from abc import ABC, abstractmethod
from typing import Any

from db.supabase_client import (
    get_cached_rate_entry,
    release_rate_refresh_lease,
    set_cached_rate,
    try_acquire_rate_refresh_lease,
)
from config import DAILY_REFRESH_HOUR_UB

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
    # Compatibility flag above is retained for third-party providers. New code
    # uses this explicit policy: live (five minutes), hourly, or daily.
    REFRESH_POLICY: str = "live"
    # Providers can override the default live interval when their source is
    # useful more frequently than the standard five-minute cache.
    REFRESH_INTERVAL_SECONDS: int | None = None
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

    def _policy(self) -> str:
        return "daily" if self.CACHE_DAILY else self.REFRESH_POLICY

    def _refresh_interval_seconds(self) -> int:
        if self.REFRESH_INTERVAL_SECONDS is not None:
            return self.REFRESH_INTERVAL_SECONDS
        return 3600 if self._policy() == "hourly" else 300

    def is_fresh(self, fetched_at: datetime, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        policy = self._policy()
        if policy == "daily":
            ub = timezone(timedelta(hours=8))
            today_window = now.astimezone(ub).replace(
                hour=DAILY_REFRESH_HOUR_UB, minute=0, second=0, microsecond=0
            )
            # Before today's window, a snapshot from yesterday remains valid.
            required_window = today_window if now.astimezone(ub) >= today_window else today_window - timedelta(days=1)
            return fetched_at.astimezone(ub) >= required_window
        return now - fetched_at <= timedelta(seconds=self._refresh_interval_seconds())

    def next_refresh_at(self, fetched_at: datetime | None = None) -> datetime:
        fetched_at = fetched_at or datetime.now(timezone.utc)
        if self._policy() == "daily":
            ub = timezone(timedelta(hours=8))
            local = fetched_at.astimezone(ub)
            due = local.replace(hour=DAILY_REFRESH_HOUR_UB, minute=0, second=0, microsecond=0)
            if local >= due:
                due += timedelta(days=1)
            return due.astimezone(timezone.utc)
        return fetched_at + timedelta(seconds=self._refresh_interval_seconds())

    def _cacheable(self, data: dict[str, Any], symbol: str) -> bool:
        return any(data.get(field) is not None for field in self.formula_fields(symbol))

    def get_rate(self, symbol: str) -> dict[str, Any]:
        """Serve a fresh shared snapshot, refreshing only when it is due."""
        try:
            cached = get_cached_rate_entry(self.NAME, symbol, include_stale=True)
            if cached and self.is_fresh(cached[1]):
                return cached[0]
        except Exception as exc:
            log.warning("Cache read error %s/%s: %s", self.NAME, symbol, exc)
            cached = None
        return self.refresh_rate(symbol, stale=cached)

    def refresh_rate(
        self, symbol: str, *, force: bool = False,
        stale: tuple[dict[str, Any], datetime] | None = None,
    ) -> dict[str, Any]:
        """Fetch once under a DB lease; retain a good stale snapshot on error."""
        if stale is None:
            try:
                stale = get_cached_rate_entry(self.NAME, symbol, include_stale=True)
            except Exception:
                stale = None
        try:
            claimed = try_acquire_rate_refresh_lease(self.NAME, symbol)
        except Exception as exc:
            # Allows deploys before the SQL migration; in-process lock still
            # prevents duplicate work inside a single bot/API container.
            log.warning("Refresh lease unavailable %s/%s: %s", self.NAME, symbol, exc)
            claimed = _daily_lock(self.NAME, symbol).acquire(blocking=False)
            local_lock = True
        else:
            local_lock = False
        if not claimed:
            return stale[0] if stale else {"lines": [f"{self.NAME} {symbol}: refresh in progress"]}
        try:
            data = self.fetch(symbol)
            if self._cacheable(data, symbol):
                set_cached_rate(self.NAME, symbol, data, next_refresh_at=self.next_refresh_at())
                return data
            return stale[0] if stale and self._cacheable(stale[0], symbol) else data
        finally:
            try:
                if local_lock:
                    _daily_lock(self.NAME, symbol).release()
                else:
                    release_rate_refresh_lease(self.NAME, symbol)
            except Exception as exc:
                log.warning("Refresh lease release failed %s/%s: %s", self.NAME, symbol, exc)

    def fetch_many(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Optional batch contract; shared-feed providers override this."""
        return {symbol: self.fetch(symbol) for symbol in symbols}

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
