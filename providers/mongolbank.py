"""
providers.mongolbank – Mongol Bank (central bank) exchange rate fetcher.

Uses the monxansh.appspot.com API which pulls official MongolBank rates:
  https://monxansh.appspot.com/xansh.json?currency=RUB

Returns the official MongolBank RUB/MNT rate.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from db.supabase_client import get_cached_rate, set_cached_rate

log = logging.getLogger(__name__)

_API_URL = "https://monxansh.appspot.com/xansh.json?currency=RUB"

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

    # Find the RUB entry
    for entry in data:
        if entry.get("code") == "RUB":
            rate = entry.get("rate_float") or entry.get("rate")
            if rate is not None:
                result = {
                    "rate": float(rate),
                    "date": entry.get("rate_date", ""),
                }
                set_cached_rate(_PROVIDER_NAME, "RUB", result)
                return result

    return {"error": "RUB rate not found"}
