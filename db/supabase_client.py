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

from config import SUPABASE_URL, SUPABASE_KEY, SUPABASE_STORAGE_KEY, CACHE_TTL, REFRESH_LEASE_SECONDS

log = logging.getLogger(__name__)

_client: Client | None = None
_storage_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def _get_storage_client() -> Client:
    global _storage_client
    if _storage_client is None:
        _storage_client = create_client(SUPABASE_URL, SUPABASE_STORAGE_KEY)
    return _storage_client


# ── Users ──────────────────────────────────────────────────────────────

def ensure_user(telegram_id: int, username: str | None = None) -> None:
    """Insert user row if it doesn't exist yet (idempotent upsert)."""
    sb = _get_client()
    sb.table("users").upsert(
        {"telegram_id": telegram_id, "username": username or ""},
        on_conflict="telegram_id",
    ).execute()


def get_rate_alerts_enabled(telegram_id: int) -> bool:
    result = (
        _get_client().table("users").select("rate_alerts_enabled")
        .eq("telegram_id", telegram_id).limit(1).execute()
    )
    if not result.data:
        return True
    return bool(result.data[0].get("rate_alerts_enabled", True))


def set_rate_alerts_enabled(telegram_id: int, enabled: bool) -> bool:
    result = (
        _get_client().table("users")
        .update({"rate_alerts_enabled": bool(enabled)})
        .eq("telegram_id", telegram_id).execute()
    )
    return bool(result.data)


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

    def usable(data: Any) -> bool:
        # Providers expose different numeric fields (rate, buy/sell, cash,
        # non-cash). Error payloads contain only display lines.
        return isinstance(data, dict) and any(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for field, value in data.items()
            if field != "lines"
        )

    if key in _mem_cache:
        fetched_at, data = _mem_cache[key]
        if (
            fetched_at.astimezone(local_tz).date() == now.date()
            and usable(data)
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
    # Error payloads must never satisfy an all-day provider cache.
    if not usable(data):
        return None
    _mem_cache[key] = (fetched_at, data)
    return data  # type: ignore[return-value]


def set_cached_rate(
    provider: str, symbol: str, rate_data: dict[str, Any], *,
    next_refresh_at: datetime | None = None,
    source_updated_at: datetime | None = None,
) -> None:
    """Upsert a rate into the cache (in-memory + Supabase)."""
    now = datetime.now(timezone.utc)
    # Preserve the prior shared snapshot before overwriting it.  Alert history
    # is best-effort: cache availability must never depend on alert storage.
    try:
        previous = get_cached_rate_entry(provider, symbol, include_stale=True)
    except Exception as exc:
        log.warning("Cannot read previous alert snapshot %s/%s: %s", provider, symbol, exc)
        previous = None
    _mem_cache[(provider, symbol)] = (now, rate_data)
    sb = _get_client()
    sb.table("cached_rates").upsert(
        {
            "provider": provider,
            "symbol": symbol,
            "rate_data": json.dumps(rate_data),
            "fetched_at": now.isoformat(),
            "next_refresh_at": next_refresh_at.isoformat() if next_refresh_at else None,
            "source_updated_at": source_updated_at.isoformat() if source_updated_at else None,
            "refresh_lock_until": None,
        },
        on_conflict="provider,symbol",
    ).execute()
    try:
        _record_rate_alerts(provider, symbol, rate_data, previous[0] if previous else None, now)
    except Exception as exc:
        log.warning("Cannot record rate alerts for %s/%s: %s", provider, symbol, exc)


def _record_rate_alerts(
    provider: str,
    symbol: str,
    rate_data: dict[str, Any],
    previous_data: dict[str, Any] | None,
    observed_at: datetime,
) -> None:
    """Persist displayed-field observations and enqueue qualifying alerts."""
    from services.rate_alerts import canonical_values, sudden_change

    values = canonical_values(rate_data)
    if not values:
        return
    previous_values = canonical_values(previous_data or {})
    sb = _get_client()
    for field, current in values.items():
        rows = (
            sb.table("rate_observations")
            .select("value")
            .eq("provider", provider).eq("symbol", symbol).eq("field", field)
            .order("observed_at", desc=True).limit(30).execute().data
        )
        # Query returns newest first; volatility needs chronological values.
        history = [Decimal(str(row["value"])) for row in reversed(rows)]
        previous = previous_values.get(field)
        detected = (
            sudden_change(provider, symbol, previous, current, history)
            if previous is not None else None
        )
        sb.table("rate_observations").upsert({
            "provider": provider, "symbol": symbol, "field": field,
            "value": str(current), "observed_at": observed_at.isoformat(),
        }, on_conflict="provider,symbol,field,observed_at").execute()
        if detected is None:
            continue
        move, threshold = detected
        subscriptions = (
            sb.table("user_subscriptions").select("id,telegram_id")
            .eq("provider", provider).eq("symbol", symbol).execute().data
        )
        for subscription in subscriptions:
            user_row = (
                sb.table("users").select("rate_alerts_enabled")
                .eq("telegram_id", subscription["telegram_id"]).limit(1).execute().data
            )
            if user_row and user_row[0].get("rate_alerts_enabled") is False:
                continue
            sb.table("rate_alerts").upsert({
                "subscription_id": subscription["id"],
                "telegram_id": subscription["telegram_id"],
                "provider": provider, "symbol": symbol, "field": field,
                "old_value": str(previous), "new_value": str(current),
                "change_percent": str(move), "threshold_percent": str(threshold),
                "observed_at": observed_at.isoformat(),
            }, on_conflict="subscription_id,field,observed_at").execute()


def get_pending_rate_alerts(limit: int = 100) -> list[dict[str, Any]]:
    result = (
        _get_client().table("rate_alerts").select("*")
        .eq("status", "pending").order("created_at").limit(limit).execute()
    )
    return result.data  # type: ignore[return-value]


def mark_rate_alert_sent(alert_id: str) -> None:
    sb = _get_client()
    row = sb.table("rate_alerts").select("attempts").eq("id", alert_id).execute()
    attempts = int(row.data[0]["attempts"]) + 1 if row.data else 1
    sb.table("rate_alerts").update({
        "status": "sent", "sent_at": datetime.now(timezone.utc).isoformat(),
        "attempts": attempts,
    }).eq("id", alert_id).eq("status", "pending").execute()


def mark_rate_alert_failed(alert_id: str, error: str, *, permanent: bool = False) -> None:
    """Keep transient Telegram failures queued; terminal chat failures stop retrying."""
    sb = _get_client()
    row = sb.table("rate_alerts").select("attempts").eq("id", alert_id).execute()
    attempts = int(row.data[0]["attempts"]) + 1 if row.data else 1
    sb.table("rate_alerts").update({
        "status": "failed" if permanent else "pending",
        "attempts": attempts, "last_error": error[:500],
    }).eq("id", alert_id).eq("status", "pending").execute()


def try_acquire_rate_refresh_lease(provider: str, symbol: str) -> bool:
    """Claim the database lease used to deduplicate upstream fetches."""
    result = _get_client().rpc("claim_rate_refresh_lease", {
        "p_provider": provider, "p_symbol": symbol,
        "p_lease_seconds": REFRESH_LEASE_SECONDS,
    }).execute()
    return bool(result.data)


def release_rate_refresh_lease(provider: str, symbol: str) -> None:
    _get_client().rpc("release_rate_refresh_lease", {
        "p_provider": provider, "p_symbol": symbol,
    }).execute()


def get_all_active_rate_pairs() -> set[tuple[str, str]]:
    """Return the unique watchlist and enabled-formula dependencies."""
    sb = _get_client()
    pairs = {
        (row["provider"], row["symbol"])
        for row in sb.table("user_subscriptions").select("provider,symbol").execute().data
    }
    for formula in get_formula_definitions(include_disabled=False):
        for operand in (formula["left_operand"], formula["right_operand"]):
            if operand.get("kind") == "rate":
                pairs.add((operand["provider"], operand["symbol"]))
    return pairs


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

def get_app_settings() -> dict[str, Any]:
    result = (
        _get_client()
        .table("app_settings")
        .select("calculator_mode,updated_at")
        .eq("singleton", True)
        .limit(1)
        .execute()
    )
    row = result.data[0] if result.data else {}
    return {
        "calculatorMode": row.get("calculator_mode") or "tape",
        "updatedAt": row.get("updated_at"),
    }


def set_calculator_mode(mode: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    result = (
        _get_client()
        .table("app_settings")
        .upsert(
            {"singleton": True, "calculator_mode": mode, "updated_at": now},
            on_conflict="singleton",
        )
        .execute()
    )
    row = result.data[0] if result.data else {"calculator_mode": mode, "updated_at": now}
    return {"calculatorMode": row.get("calculator_mode", mode), "updatedAt": row.get("updated_at", now)}


# ── Global branding ───────────────────────────────────────────────────

def _public_branding_url(path: str | None) -> str | None:
    if not path:
        return None
    return _get_storage_client().storage.from_("branding").get_public_url(path)


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
    _get_storage_client().storage.from_("branding").upload(
        path,
        content,
        file_options={"content-type": "image/webp"},
    )


def delete_branding_asset(path: str) -> None:
    _get_storage_client().storage.from_("branding").remove([path])
