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
import uuid
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
    """Return subscription rows for this user."""
    sb = _get_client()
    result = (
        sb.table("user_subscriptions")
        .select("id, provider, symbol")
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


def remove_subscription_by_id(telegram_id: int, subscription_id: str) -> bool:
    """Remove one subscription only when it belongs to the current user."""
    sb = _get_client()
    result = (
        sb.table("user_subscriptions")
        .delete()
        .eq("id", subscription_id)
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return bool(result.data)


# ── Whitelist ──────────────────────────────────────────────────────────

def is_whitelisted(telegram_id: int) -> bool:
    sb = _get_client()
    result = (
        sb.table("whitelist")
        .select("telegram_id")
        .eq("telegram_id", telegram_id)
        .execute()
    )
    return bool(result.data)


def add_to_whitelist(telegram_id: int) -> bool:
    """Add a user to the whitelist. Returns False if already present."""
    sb = _get_client()
    existing = (
        sb.table("whitelist")
        .select("telegram_id")
        .eq("telegram_id", telegram_id)
        .execute()
    )
    if existing.data:
        return False
    sb.table("whitelist").insert({"telegram_id": telegram_id}).execute()
    return True


def remove_from_whitelist(telegram_id: int) -> bool:
    """Remove a user from the whitelist. Returns False if not found."""
    sb = _get_client()
    existing = (
        sb.table("whitelist")
        .select("telegram_id")
        .eq("telegram_id", telegram_id)
        .execute()
    )
    if not existing.data:
        return False
    sb.table("whitelist").delete().eq("telegram_id", telegram_id).execute()
    return True


def get_whitelist() -> list[int]:
    sb = _get_client()
    result = sb.table("whitelist").select("telegram_id").execute()
    return [row["telegram_id"] for row in result.data]


# ── Rate Cache ─────────────────────────────────────────────────────────

# In-memory cache: {(provider, symbol): (fetched_at, rate_data)}
_mem_cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}


def get_cached_rate_entry(
    provider: str,
    symbol: str,
    *,
    include_stale: bool = False,
) -> tuple[dict[str, Any], datetime] | None:
    """Return cached data and its timestamp.

    Checks an in-memory dict first to avoid Supabase round-trips,
    then falls back to the remote table. Stale entries are returned only when
    explicitly requested, which lets the web UI preserve the last good value.
    """
    now = datetime.now(timezone.utc)
    key = (provider, symbol)
    ttl = timedelta(seconds=CACHE_TTL)

    # 1. In-memory check (fast path)
    if key in _mem_cache:
        ts, data = _mem_cache[key]
        if include_stale or now - ts <= ttl:
            return data, ts

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
    if not include_stale and now - fetched_at > ttl:
        return None
    data = row.data[0]["rate_data"]
    if isinstance(data, str):
        data = json.loads(data)
    # Warm in-memory cache from Supabase hit
    _mem_cache[key] = (fetched_at, data)
    return data, fetched_at  # type: ignore[return-value]


def get_cached_rate(provider: str, symbol: str) -> dict[str, Any] | None:
    """Return cached rate_data dict if fresh, else None."""
    entry = get_cached_rate_entry(provider, symbol)
    return entry[0] if entry else None


def get_daily_cached_rate(
    provider: str,
    symbol: str,
    utc_offset_hours: int = 8,
) -> dict[str, Any] | None:
    """Return a cached payload only when it was stored on the local current day.

    This is intended for daily-published bank rates.  It deliberately ignores
    ``CACHE_TTL`` so the same daily snapshot can be served without refetching
    on every /rates request.
    """
    local_tz = timezone(timedelta(hours=utc_offset_hours))
    now = datetime.now(local_tz)
    key = (provider, symbol)

    if key in _mem_cache:
        fetched_at, data = _mem_cache[key]
        if (
            fetched_at.astimezone(local_tz).date() == now.date()
            and "rate" in data
        ):
            return data

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

    fetched_at = datetime.fromisoformat(row.data[0]["fetched_at"].replace("Z", "+00:00"))
    if fetched_at.astimezone(local_tz).date() != now.date():
        return None

    data = row.data[0]["rate_data"]
    if isinstance(data, str):
        data = json.loads(data)
    # A manual refresh can write an error payload through the generic cache
    # path.  Error payloads must never satisfy the all-day MongolBank cache.
    if not isinstance(data, dict) or "rate" not in data:
        return None
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


# ── Short-lived share bundles ─────────────────────────────────────────

def create_share_bundle(
    telegram_id: int,
    token: str,
    payload: dict[str, Any],
    expires_at: datetime,
) -> None:
    sb = _get_client()
    # Opportunistic cleanup keeps the short-lived table bounded without a
    # separate scheduler or database extension.
    sb.table("share_bundles").delete().lt(
        "expires_at", datetime.now(timezone.utc).isoformat()
    ).execute()
    sb.table("share_bundles").insert(
        {
            "token": token,
            "telegram_id": telegram_id,
            "payload": json.dumps(payload),
            "expires_at": expires_at.isoformat(),
        }
    ).execute()


def get_share_bundle(telegram_id: int, token: str) -> dict[str, Any] | None:
    sb = _get_client()
    result = (
        sb.table("share_bundles")
        .select("payload, expires_at")
        .eq("token", token)
        .eq("telegram_id", telegram_id)
        .execute()
    )
    if not result.data:
        return None
    row = result.data[0]
    expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    if expires_at <= datetime.now(timezone.utc):
        sb.table("share_bundles").delete().eq("token", token).execute()
        return None
    payload = row["payload"]
    return json.loads(payload) if isinstance(payload, str) else payload


# ── Global calculated formulas ────────────────────────────────────────

def get_formula_definitions(*, include_disabled: bool = True) -> list[dict[str, Any]]:
    sb = _get_client()
    query = (
        sb.table("calculated_formulas")
        .select(
            "id,title,left_operand,operator,right_operand,adjustment_percent,"
            "precision,enabled,sort_order,created_at,updated_at"
        )
        .is_("deleted_at", "null")
    )
    if not include_disabled:
        query = query.eq("enabled", True)
    result = query.order("sort_order").order("created_at").execute()
    return result.data  # type: ignore[return-value]


def create_formula_definition(data: dict[str, Any]) -> dict[str, Any]:
    sb = _get_client()
    formula_id = str(uuid.uuid4())
    current = get_formula_definitions()
    row = {
        **data,
        "id": formula_id,
        "sort_order": max((int(item["sort_order"]) for item in current), default=-1) + 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = sb.table("calculated_formulas").insert(row).execute()
    return result.data[0]  # type: ignore[return-value]


def update_formula_definition(formula_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    sb = _get_client()
    result = (
        sb.table("calculated_formulas")
        .update({**data, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", formula_id)
        .is_("deleted_at", "null")
        .execute()
    )
    return result.data[0] if result.data else None


def reorder_formula_definitions(ids: list[str]) -> list[dict[str, Any]]:
    sb = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    for index, formula_id in enumerate(ids):
        (
            sb.table("calculated_formulas")
            .update({"sort_order": index, "updated_at": now})
            .eq("id", formula_id)
            .is_("deleted_at", "null")
            .execute()
        )
    return get_formula_definitions()


def soft_delete_formula_definition(formula_id: str) -> bool:
    sb = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    result = (
        sb.table("calculated_formulas")
        .update({"deleted_at": now, "updated_at": now})
        .eq("id", formula_id)
        .is_("deleted_at", "null")
        .execute()
    )
    return bool(result.data)


# ── Global branding ───────────────────────────────────────────────────

def _public_branding_url(path: str | None) -> str | None:
    if not path:
        return None
    return _get_client().storage.from_("branding").get_public_url(path)


def get_branding() -> dict[str, Any]:
    sb = _get_client()
    app_result = (
        sb.table("app_branding")
        .select("logo_path,updated_at")
        .eq("singleton", True)
        .limit(1)
        .execute()
    )
    source_result = (
        sb.table("source_branding")
        .select("provider,logo_path,updated_at")
        .execute()
    )
    app_row = app_result.data[0] if app_result.data else {}
    app_path = app_row.get("logo_path")
    sources = {
        row["provider"]: {
            "url": _public_branding_url(row.get("logo_path")),
            "updatedAt": row.get("updated_at"),
        }
        for row in source_result.data
        if row.get("logo_path")
    }
    return {
        "appLogoUrl": _public_branding_url(app_path),
        "appUpdatedAt": app_row.get("updated_at"),
        "sourceLogos": sources,
    }


def get_branding_path(provider: str | None = None) -> str | None:
    sb = _get_client()
    if provider is None:
        result = (
            sb.table("app_branding")
            .select("logo_path")
            .eq("singleton", True)
            .limit(1)
            .execute()
        )
    else:
        result = (
            sb.table("source_branding")
            .select("logo_path")
            .eq("provider", provider)
            .limit(1)
            .execute()
        )
    return result.data[0].get("logo_path") if result.data else None


def set_branding_path(path: str | None, provider: str | None = None) -> None:
    sb = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    if provider is None:
        (
            sb.table("app_branding")
            .upsert(
                {"singleton": True, "logo_path": path, "updated_at": now},
                on_conflict="singleton",
            )
            .execute()
        )
    else:
        (
            sb.table("source_branding")
            .upsert(
                {"provider": provider, "logo_path": path, "updated_at": now},
                on_conflict="provider",
            )
            .execute()
        )


def upload_branding_asset(path: str, content: bytes) -> None:
    _get_client().storage.from_("branding").upload(
        path,
        content,
        file_options={"content-type": "image/webp", "upsert": "true"},
    )


def delete_branding_asset(path: str) -> None:
    _get_client().storage.from_("branding").remove([path])
