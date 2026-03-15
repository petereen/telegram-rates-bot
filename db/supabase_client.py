"""
db.supabase_client – thin wrapper around Supabase for users, subscriptions
and the rate cache.

Tables expected in Supabase:
  users(telegram_id bigint PK, username text, created_at timestamptz)
  user_subscriptions(id uuid PK default gen_random_uuid(),
                     telegram_id bigint FK -> users,
                     provider text, symbol text,
                     created_at timestamptz)
  cached_rates(provider text, symbol text, rate_data jsonb,
               fetched_at timestamptz,
               PK (provider, symbol))
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from supabase import create_client, Client

from config import SUPABASE_URL, SUPABASE_KEY, CACHE_TTL

log = logging.getLogger(__name__)

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ── Users ──────────────────────────────────────────────────────────────

def ensure_user(telegram_id: int, username: str | None = None) -> None:
    """Insert user row if it doesn't exist yet (idempotent upsert)."""
    sb = _get_client()
    sb.table("users").upsert(
        {"telegram_id": telegram_id, "username": username or ""},
        on_conflict="telegram_id",
    ).execute()


# ── Subscriptions ──────────────────────────────────────────────────────

def add_subscription(telegram_id: int, provider: str, symbol: str) -> bool:
    """Add a pair to the user's watchlist.  Returns False if duplicate."""
    sb = _get_client()
    existing = (
        sb.table("user_subscriptions")
        .select("id")
        .eq("telegram_id", telegram_id)
        .eq("provider", provider)
        .eq("symbol", symbol)
        .execute()
    )
    if existing.data:
        return False
    sb.table("user_subscriptions").insert(
        {"telegram_id": telegram_id, "provider": provider, "symbol": symbol}
    ).execute()
    return True


def remove_subscription(telegram_id: int, provider: str, symbol: str) -> bool:
    """Remove a pair from the user's watchlist.  Returns False if not found."""
    sb = _get_client()
    existing = (
        sb.table("user_subscriptions")
        .select("id")
        .eq("telegram_id", telegram_id)
        .eq("provider", provider)
        .eq("symbol", symbol)
        .execute()
    )
    if not existing.data:
        return False
    sb.table("user_subscriptions").delete().eq(
        "id", existing.data[0]["id"]
    ).execute()
    return True


def get_subscriptions(telegram_id: int) -> list[dict[str, str]]:
    """Return list of {provider, symbol} dicts for this user."""
    sb = _get_client()
    result = (
        sb.table("user_subscriptions")
        .select("provider, symbol")
        .eq("telegram_id", telegram_id)
        .order("provider")
        .execute()
    )
    return result.data  # type: ignore[return-value]


def clear_subscriptions(telegram_id: int) -> int:
    """Delete all subscriptions for a user.  Returns count removed."""
    sb = _get_client()
    result = (
        sb.table("user_subscriptions")
        .delete()
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return len(result.data) if result.data else 0


# ── All users (paginated) ─────────────────────────────────────────────

_PAGE_SIZE = 1000


def get_all_user_ids() -> list[int]:
    """Return every telegram_id from the users table, paginating past the 1000-row limit."""
    sb = _get_client()
    ids: list[int] = []
    offset = 0
    while True:
        result = (
            sb.table("users")
            .select("telegram_id")
            .range(offset, offset + _PAGE_SIZE - 1)
            .execute()
        )
        if not result.data:
            break
        ids.extend(row["telegram_id"] for row in result.data)
        if len(result.data) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return ids


# ── Rate Cache ─────────────────────────────────────────────────────────

# In-memory cache: {(provider, symbol): (fetched_at, rate_data)}
_mem_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}


def get_cached_rate(provider: str, symbol: str) -> dict[str, Any] | None:
    """Return cached rate_data dict if fresh, else None.

    Checks an in-memory dict first to avoid Supabase round-trips,
    then falls back to the remote table.
    """
    now = datetime.now(timezone.utc)
    key = (provider, symbol)
    ttl = timedelta(seconds=CACHE_TTL)

    # 1. In-memory check (fast path)
    if key in _mem_cache:
        ts, data = _mem_cache[key]
        if now - ts <= ttl:
            return data

    # 2. Supabase fallback
    sb = _get_client()
    row = (
        sb.table("cached_rates")
        .select("rate_data, fetched_at")
        .eq("provider", provider)
        .eq("symbol", symbol)
        .execute()
    )
    if not row.data:
        return None
    fetched_at_str: str = row.data[0]["fetched_at"]
    fetched_at = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))
    if now - fetched_at > ttl:
        return None
    data = row.data[0]["rate_data"]
    if isinstance(data, str):
        data = json.loads(data)
    # Warm in-memory cache from Supabase hit
    _mem_cache[key] = (fetched_at, data)
    return data  # type: ignore[return-value]


def set_cached_rate(provider: str, symbol: str, rate_data: dict[str, Any]) -> None:
    """Upsert a rate into the cache (in-memory + Supabase)."""
    now = datetime.now(timezone.utc)
    _mem_cache[(provider, symbol)] = (now, rate_data)
    sb = _get_client()
    sb.table("cached_rates").upsert(
        {
            "provider": provider,
            "symbol": symbol,
            "rate_data": json.dumps(rate_data),
            "fetched_at": now.isoformat(),
        },
        on_conflict="provider,symbol",
    ).execute()
