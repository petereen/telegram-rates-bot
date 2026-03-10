"""
providers.tdb – TDB Bank (Худалдаа Хөгжлийн Банк) exchange rate fetcher.

Uses the community API at:
  https://mongolian-bank-exchange-rate-6620c122ff22.herokuapp.com/rates/bank/TDBM

Returns TDB Bank non-cash USD selling rate.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from db.supabase_client import get_cached_rate, set_cached_rate

log = logging.getLogger(__name__)

_API_URL = (
    "https://mongolian-bank-exchange-rate-6620c122ff22.herokuapp.com"
    "/rates/bank/TDBM"
)

_PROVIDER_NAME = "TDBM"


def fetch_tdb_usd_noncash_sell() -> dict[str, Any]:
    """Fetch the TDB Bank non-cash USD selling rate (MNT per 1 USD).

    Returns dict with 'rate' key on success, or 'error' key on failure.
    Uses the shared cache (TTL from config).
    """
    cached = get_cached_rate(_PROVIDER_NAME, "USD_NONCASH_SELL")
    if cached is not None:
        log.debug("Cache hit  %s/USD_NONCASH_SELL", _PROVIDER_NAME)
        return cached

    log.info("Fetching   %s/USD_NONCASH_SELL", _PROVIDER_NAME)
    try:
        resp = requests.get(_API_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.error("TDB Bank fetch error: %s", exc)
        return {"error": "fetch error"}

    if not data or not isinstance(data, list):
        return {"error": "unexpected response"}

    # Take the most recent entry (first in the list)
    latest = data[0]
    rates = latest.get("rates", {})
    usd = rates.get("usd", {})

    noncash_sell = usd.get("noncash", {}).get("sell")
    if noncash_sell is None:
        return {"error": "USD noncash sell rate not found"}

    result = {"rate": float(noncash_sell), "date": latest.get("date", "")}
    set_cached_rate(_PROVIDER_NAME, "USD_NONCASH_SELL", result)
    return result
