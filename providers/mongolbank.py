"""
providers.mongolbank – Mongol Bank (central bank) exchange rate fetcher.

Uses the community API at:
  https://mongolian-bank-exchange-rate-6620c122ff22.herokuapp.com/rates/bank/MongolBank

Returns the official MongolBank RUB/MNT rate.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from db.supabase_client import get_cached_rate, set_cached_rate

log = logging.getLogger(__name__)

_API_URL = (
    "https://mongolian-bank-exchange-rate-6620c122ff22.herokuapp.com"
    "/rates/bank/MongolBank"
)

_PROVIDER_NAME = "MongolBank"


def fetch_mongolbank_rub_rate() -> dict[str, Any]:
    """Fetch the MongolBank RUB rate (MNT per 1 RUB).

    Returns dict with 'rate' key on success, or 'error' key on failure.
    Uses the shared cache (TTL from config).
    """
    cached = get_cached_rate(_PROVIDER_NAME, "RUB")
    if cached is not None:
        log.debug("Cache hit  %s/RUB", _PROVIDER_NAME)
        return cached

    log.info("Fetching   %s/RUB", _PROVIDER_NAME)
    try:
        resp = requests.get(_API_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.error("MongolBank fetch error: %s", exc)
        return {"error": "fetch error"}

    if not data or not isinstance(data, list):
        return {"error": "unexpected response"}

    # Take the most recent entry (first in the list)
    latest = data[0]
    rates = latest.get("rates", {})
    rub = rates.get("rub", {})

    # MongolBank is the central bank – buy == sell (reference rate)
    rate = rub.get("cash", {}).get("sell")
    if rate is None:
        rate = rub.get("noncash", {}).get("sell")
    if rate is None:
        return {"error": "RUB rate not found"}

    result = {"rate": float(rate), "date": latest.get("date", "")}
    set_cached_rate(_PROVIDER_NAME, "RUB", result)
    return result
